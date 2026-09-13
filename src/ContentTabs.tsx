import { DialogBody, DialogControlsSection, SidebarNavigation, SidebarNavigationPage, Tab, Tabs } from "@decky/ui";
import { FC, useEffect, useState } from "react";
import { ActionSet, ContentType, ContentError, ContentResult, ExecuteArgs, ExecuteGetContentArgs, StoreContent, StoreTabsContent, GameDataList } from "./Types/Types";
import Logger from "./Utils/logger";
import { executeAction } from "./Utils/executeAction";
import { Loading } from "./Components/Loading";
import { ErrorDisplay } from "./Components/ErrorDisplay";
import { GridContent, contentTabsContainerClass } from "./Components/GridContent";
import { HtmlContent } from "./HtmlContent";
import { TextContent } from "./TextContent";
import { MainMenu } from "./MainMenu";
import { useCachedState } from './hooks/useCachedState';
import { gamepadLibraryClasses } from './staticClasses';
interface ContentTabsProperties {
    
    content: StoreTabsContent;
    initActionSet: string;
    initAction: string;
    layout: 'horizontal' | 'vertical';
    subActionSet: string;
}
export interface StoreTabsState {
    currentTab: string;
}

export const ContentTabs: FC<ContentTabsProperties> = ({ content, initAction, initActionSet, layout, subActionSet }) => {
    const { cacheState: cacheData, setCacheState: setCacheData } = useCachedState(initActionSet, initAction, 'tabcontent', { currentTab: "-1" });

    const getTabs: () => Tab[] = () => {
        return content.Tabs.map((tab, index) => ({
            title: tab.Title,
            content: <Content key={tab.ActionId} initActionSet={subActionSet} initAction={tab.ActionId} />,
            id: index.toString()
        }));
    };

    const getPages: () => SidebarNavigationPage[] = () => {
        return content.Tabs.map((tab) => ({
            title: tab.Title,
            content: <Content key={tab.ActionId} initActionSet={subActionSet} initAction={tab.ActionId} />,
            identifier: tab.Title,
            hideTitle: true
        }));
    };

    return (
        <DialogBody key={initActionSet + "_" + initAction} className={contentTabsContainerClass}>
            {content.Tabs.length === 0 ? <Loading /> : (layout === "horizontal" ? (
                <DialogControlsSection key={initActionSet + "_" + initAction + "horizontal"} className={gamepadLibraryClasses.GamepadLibrary}>
                    <Tabs
                        key="0"
                        activeTab={cacheData.currentTab}
                        onShowTab={(tabID: string) => setCacheData({ currentTab: tabID })}
                        tabs={getTabs()}
                        autoFocusContents={true}
                        //@ts-ignore
                        canBeHeaderBackground={'always'}
                    />
                </DialogControlsSection>
            ) : (
                <DialogControlsSection key={initActionSet + "_" + initAction + "vertical"} style={{ height: "100%" }}>
                    <SidebarNavigation key="1" pages={getPages()} />
                </DialogControlsSection>
            ))}
        </DialogBody>
    );
};

// In-memory content cache: avoids re-fetching game lists on tab switches
const contentCache: Map<string, { data: ContentResult<ContentType>; actionSet: string; time: number }> = new Map();
const CONTENT_CACHE_TTL = 5 * 60 * 1000; // 5 minutes

export const Content: FC<{  initActionSet: string; initAction: string; closeModal?: ()=>void}> = ({ initActionSet, initAction, closeModal }) => {
    const logger = new Logger("Content");
    const [content, setContent] = useState<ContentResult<ContentType>>({ Type: "Empty", Content: {} });
    const [actionSetName, setActionSetName] = useState("");

    const { cacheState: gridContentCache, setCacheState: setGridContentCache, hadCache: hadGridCache } = useCachedState(
        initActionSet,
        initAction,
        'gridcontentparams',
        {
            filter: "",
            installed: false,
        }
    );

    useEffect(() => {
        (async () => {
            try {
                // Check in-memory cache first
                const cacheKey = `${initActionSet}_${initAction}_${JSON.stringify(hadGridCache ? gridContentCache : {})}`;
                const cached = contentCache.get(cacheKey);
                if (cached && (Date.now() - cached.time) < CONTENT_CACHE_TTL) {
                    setActionSetName(cached.actionSet);
                    setContent(cached.data);
                    return;
                }

                logger.debug(`Initializing Content with initActionSet: ${initActionSet} and initAction: ${initAction}`);
                const actionSetRes = await executeAction<ExecuteArgs,ActionSet>(initActionSet, initAction, {});
                logger.debug("init result: ", actionSetRes);
                if (actionSetRes === null) return;

                const actionSet = actionSetRes.Content;
                const contentRes = await getContent(actionSet.SetName, hadGridCache ? stringifyArgs(gridContentCache) : {});
                if (contentRes === null) return;

                setActionSetName(actionSet.SetName);
                setContent(contentRes);

                // Store in cache
                contentCache.set(cacheKey, { data: contentRes, actionSet: actionSet.SetName, time: Date.now() });
            } catch (error) {
                logger.error("OnInit: ", error);
            }
        })();
    }, []);

    const getContent = async (actionSet: string, actionArgs: { [param: string]: string; }) => executeAction<ExecuteGetContentArgs, ContentResult<ContentType>>(actionSet, "GetContent", actionArgs);

    const refreshContent = (args: { [param: string]: any; }, onFinish?: () => void) => {
        (async () => {
            logger.debug("Refreshing Content with args: ", args);
            const contentRes = await getContent(actionSetName, stringifyArgs(args));
            if (contentRes !== null) {
                setContent(contentRes);
                // Update cache with fresh data
                const cacheKey = `${initActionSet}_${initAction}_${JSON.stringify(args)}`;
                contentCache.set(cacheKey, { data: contentRes, actionSet: actionSetName, time: Date.now() });
            }
            onFinish?.();
        })();
    };

    switch (content.Type) {
        case "GameGrid":
            return <GridContent
                content={content.Content as GameDataList}
                initActionSet={actionSetName}
                refreshContent={refreshContent}
                argsCache={gridContentCache}
                setArgsCache={setGridContentCache}
            />;

        case "StoreTabs":
            return <ContentTabs
                content={content.Content as StoreTabsContent}
                layout="horizontal"
                initAction={initAction}
                initActionSet={initActionSet}
                subActionSet={actionSetName}
            />;

        case "SideBarPage":
            return <ContentTabs
                content={content.Content as StoreTabsContent}
                layout="vertical"
                initAction={initAction}
                initActionSet={initActionSet}
                subActionSet={actionSetName}
            />;

        case "MainMenu":
            return <MainMenu //key={initActionSet + "_" + initAction}
                content={content.Content as StoreContent}
                initActionSet={actionSetName}
                initAction=""
                closeModal={closeModal}
            />;

        case "Text":
            return <TextContent //key={initActionSet + "_" + initAction} 
                content={content.Content as string}
            />;

        case "Html":
            return <HtmlContent //key={initActionSet + "_" + initAction}
                content={content.Content as string}
            />;

        case "Error":
            return <ErrorDisplay //key={initActionSet + "_" + initAction}
                error={content.Content as ContentError}
            />;

        case "Empty":
            return <Loading />;

        default:
            return null;
    }
};

function stringifyArgs(args: { [param: string]: any; }) {
    let out: { [param: string]: string; } = {};
    for (let key in args) {
        out[key] = String(args[key]);
    }
    return out;
}