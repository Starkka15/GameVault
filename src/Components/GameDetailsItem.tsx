import { Focusable, ModalRoot, sleep, gamepadDialogClasses, showModal, Navigation } from "@decky/ui";
import { toaster } from "@decky/api";
import { useState, useEffect, FC, useRef } from "react";
import GameDisplay from "./GameDisplay";
import { ContentError, ContentResult, ContentType, EmptyContent, ExecuteGetGameDetailsArgs, ExecuteInstallArgs, GameDetails, GameImages, LaunchOptions, MenuAction, ProgressUpdate, ScriptActions } from "../Types/Types";
import { runApp } from "../Utils/utils";
import Logger from "../Utils/logger";
import { Loading } from "./Loading";
import { executeAction } from "../Utils/executeAction";
import { footerClasses } from '../staticClasses';
import { reaction } from 'mobx';
import { ErrorModal } from "../ErrorModal";
import { installQueue, QueueItem, QueueState } from '../Utils/installQueue';

const gameDetailsRootClass = 'game-details-modal-root';

interface GameDetailsItemProperties {

    shortname: string;
    initActionSet: string;
    closeModal?: any;
    initAction?: string;
    clearActiveGame?: () => void;
}

export const GameDetailsItem: FC<GameDetailsItemProperties> = ({ shortname, initActionSet, closeModal }) => {

    const logger = new Logger("GameDetailsItem");
    const [scriptActions, setScriptActions] = useState<MenuAction[]>([]);
    const [gameData, setGameData] = useState<ContentResult<GameDetails | EmptyContent>>({ Type: "Empty", Content: { Details: {} } });
    const [steamClientID, setSteamClientID] = useState("");

    // Queue-based download tracking
    const [queueItem, setQueueItem] = useState<QueueItem | undefined>(
        installQueue.getItemStatus(shortname)
    );

    // Local progress for non-download actions (verify, repair, save sync, etc.)
    const [localInstalling, setLocalInstalling] = useState(false);
    const [localProgress, setLocalProgress] = useState<ProgressUpdate>({
        Percentage: 0,
        Description: ""
    });
    const localInstallingRef = useRef(localInstalling);
    useEffect(() => {
        localInstallingRef.current = localInstalling;
    }, [localInstalling]);

    // Derived state: is this game downloading/installing via queue?
    const isQueueActive = queueItem && (queueItem.status === "downloading" || queueItem.status === "installing" || queueItem.status === "queued");
    const installing = localInstalling || !!isQueueActive;
    const progress: ProgressUpdate = isQueueActive
        ? { Percentage: queueItem!.progress, Description: queueItem!.description }
        : localProgress;

    const originRoute = location.pathname.replace('/routes', '');

    // Subscribe to installQueue for this game's status
    useEffect(() => {
        const unsubscribe = installQueue.subscribe((state: QueueState) => {
            const item = state.items.find(i => i.shortname === shortname);
            setQueueItem(item);
            // If queue just completed install for this game, refresh data
            if (item?.status === "done") {
                reloadData();
            }
        });
        return () => { unsubscribe(); };
    }, [shortname]);

    useEffect(() => {
        const dispose = reaction(() => SteamUIStore.WindowStore.GamepadUIMainWindowInstance?.LocationPathName, closeModal);
        onInit();
        return dispose;
    }, []);

    const reloadData = async () => {
        setGameData({ Type: "Empty", Content: { Details: {} } });
        onInit();
    };
    const onInit = async () => {
        try {
            logger.debug("onInit starting");
            const gameDetailsResponse = await executeAction<ExecuteGetGameDetailsArgs, GameDetails>(initActionSet,
                "GetDetails",
                {
                    shortname: shortname
                }
            );

            logger.debug("onInit res", gameDetailsResponse);
            if (gameDetailsResponse === null) {
                return;
            }
            setSteamClientID(gameDetailsResponse.Content.SteamClientID);
            logger.debug("onInit finished");
            const scriptActionResponse = await executeAction<ExecuteGetGameDetailsArgs, ScriptActions>(initActionSet,
                "GetGameScriptActions",
                {
                    shortname: shortname
                }
            );
            logger.debug("onInit actionRes", scriptActionResponse);
            if (scriptActionResponse === null) {
                return;
            }
            logger.debug("onInit scriptActions", scriptActionResponse.Content);
            setGameData(gameDetailsResponse);
            setScriptActions(scriptActionResponse.Content.Actions);
        } catch (error) {
            logger.error(error);
        }
    };

    // Local progress polling for non-download actions (verify, repair, etc.)
    const updateLocalProgress = async () => {
        while (localInstallingRef.current) {
            try {
                const progressUpdateResponse = await executeAction<ExecuteGetGameDetailsArgs, ProgressUpdate>(initActionSet,
                    "GetProgress",
                    {
                        shortname: shortname
                    }
                )
                if (progressUpdateResponse === null) {
                    return;
                }
                const progressUpdate = progressUpdateResponse.Content;
                if (progressUpdate != null) {
                    setLocalProgress(progressUpdate);
                    if (progressUpdate.Error != null) {
                        showModal(<ErrorModal Error={{ ActionName: "GetProgress", ActionSet: initActionSet, Message: "Installation failed", Data: progressUpdate.Error ?? "" } as ContentError} />);
                        setLocalInstalling(false);
                        break;
                    }
                    if (progressUpdate.Percentage >= 100) {
                        setLocalInstalling(false);
                        break;
                    }
                }
            } catch (e) {
                logger.error('Error in progress updater', e);
            }
            await sleep(1000);
        }
    };

    useEffect(() => {
        if (localInstalling) {
            updateLocalProgress();
        }
    }, [localInstalling]);

    const uninstall = async () => {
        try {
            await executeAction<ExecuteGetGameDetailsArgs, ContentType>(initActionSet,
                "Uninstall",
                {
                    shortname: shortname
                }
            );
            const sid = parseInt(steamClientID, 10);
            if (!Number.isNaN(sid)) SteamClient.Apps.RemoveShortcut(sid);
            setSteamClientID("");
        } catch (error) {
            logger.error(error);
        }
    };

    // Downloads go through the queue
    const download = async (update: boolean) => {
        if (update) {
            // Updates use local state since they're for already-installed games
            try {
                const result = await executeAction<ExecuteGetGameDetailsArgs, ContentType>(initActionSet,
                    "Update",
                    { shortname: shortname }
                );
                if (result?.Type == "Progress") {
                    setLocalInstalling(true);
                }
            } catch (error) {
                logger.error(error);
            }
        } else {
            // Fresh installs go through the queue
            const gameName = gameData.Type === "GameDetails"
                ? (gameData.Content as GameDetails).Name
                : shortname;
            installQueue.add(shortname, gameName, initActionSet);
        }
    };

    const onExeExit = () => {
        Navigation.CloseSideMenus();
        Navigation.Navigate(originRoute);
        const modal = showModal(<GameDetailsItem shortname={shortname} initActionSet={initActionSet} closeModal={() => modal.Close()} />);
    };

    const runScript = async (actionSet: string, actionId: string, args: any) => {
        const result = await executeAction<ExecuteGetGameDetailsArgs, ContentType>(actionSet, actionId, args, onExeExit);
        if (result?.Type == "Progress") {
            setLocalInstalling(true);
        }
    };

    const cancelInstall = async () => {
        if (isQueueActive) {
            installQueue.cancelItem(shortname);
        } else {
            localInstallingRef.current = false;
            setLocalInstalling(false);
            try {
                await executeAction(initActionSet,
                    "CancelInstall",
                    { shortname: shortname }
                );
            } catch (error) {
                logger.error(error);
            }
        }
    };

    const checkid = async () => {
        let id = parseInt(steamClientID, 10);
        logger.debug("checkid", id);
        const apps = appStore.allApps.filter(app => app.appid == id && app.per_client_data[0].client_name == "This Machine");
        if (apps.length == 0) {
            return await getSteamId();
        } else {
            return id;
        }
    };

    const resetLaunchOptions = async () => {
        let id = await checkid();
        logger.debug("resetLaunchOptions id:", id);
        configureShortcut(id);
    };

    const configureShortcut = async (id: number) => {
        const result = await executeAction<ExecuteInstallArgs, ContentType>(initActionSet,
            "Install",
            {
                shortname: shortname,
                steamClientID: id.toString()
            }
        );
        if (gameData.Type !== "GameDetails") {
            return;
        }
        const name = (gameData.Content as GameDetails).Name;

        const apps = appStore.allApps.filter(app => app.display_name == name && app.app_type == 1073741824 && app.appid != id);
        logger.debug("apps", apps);

        if (result == null) {
            logger.error("install result is null");
            return;
        }
        if (result.Type === "LaunchOptions") {
            const launchOptions = result.Content as LaunchOptions;
            await appDetailsCache.FetchDataForApp(id)
            await appDetailsStore.RequestAppDetails(id);
            SteamClient.Apps.SetAppLaunchOptions(id, launchOptions.Options);
            SteamClient.Apps.SetShortcutName(id, (gameData.Content as GameDetails).Name);
            SteamClient.Apps.SetShortcutExe(id, launchOptions.Exe);
            SteamClient.Apps.SetShortcutStartDir(id, launchOptions.WorkingDir);
            const defaultProton = settingsStore.settings.strCompatTool;
            if (launchOptions.Compatibility && launchOptions.Compatibility == true) {
                logger.debug("Setting compatibility", launchOptions.CompatToolName);
                if (defaultProton) {
                    SteamClient.Apps.SpecifyCompatTool(id, defaultProton);
                }
                else {
                    const compatTools = await SteamClient.Apps.GetAvailableCompatTools(1)
                    const firstAvailable = compatTools.filter(tool => tool.strToolName.startsWith('proton') && tool.strToolName.indexOf('experimental') == -1)
                    if (firstAvailable.length > 0) {
                        SteamClient.Apps.SpecifyCompatTool(id, firstAvailable[0].CompatToolName);
                    }
                }
            }
            else {
                logger.debug("Setting compatibility to empty string");
                SteamClient.Apps.SpecifyCompatTool(id, "");
            }
            setLocalInstalling(false);
            toaster.toast({
                title: "GameVault",
                body: "Launch options set",
            });
            await appDetailsCache.FetchDataForApp(id)
            await appDetailsStore.RequestAppDetails(id);
            setSteamClientID(id.toString());
        }
        const imageResult = await executeAction<ExecuteGetGameDetailsArgs, GameImages>(initActionSet,
            "GetJsonImages",
            {
                shortname: shortname
            }
        );
        if (imageResult == null) {
            logger.error("imageResult is null");
            return;
        }
        const images = imageResult.Content;
        logger.debug("images", images);
        if (images.Grid !== null) {
            logger.debug("setting grid image:" + id)
            await SteamClient.Apps.SetCustomArtworkForApp(id, images.Grid, 'png', 0);
        }
        if (images.Hero !== null) {
            logger.debug("setting hero image:" + id)
            await SteamClient.Apps.SetCustomArtworkForApp(id, images.Hero, "png", 1);
        }
        if (images.Logo !== null) {
            logger.debug("setting logo image:" + id)
            await SteamClient.Apps.SetCustomArtworkForApp(id, images.Logo, "png", 2);
        }
        if (images.GridH !== null) {
            logger.debug("setting gridh image:" + id)
            await SteamClient.Apps.SetCustomArtworkForApp(id, images.GridH, "png", 3);
        }
    };

    const getSteamId = async () => {
        const gameDetails = gameData.Content as GameDetails;
        const name = gameDetails.Name;
        logger.debug("GetSteamId name:", name);
        if (gameDetails.SteamClientID != "") {
            const steamClientID = parseInt(gameDetails.SteamClientID, 10);
            const apps = appStore.allApps.filter(app => app.appid == steamClientID);
            if (apps.length > 0) {
                return steamClientID;
            }
        }
        const id = await SteamClient.Apps.AddShortcut("Name", "/bin/bash", "", "");
        if (!id || id <= 0) {
            logger.error("AddShortcut returned invalid id:", id);
            throw new Error("Failed to create Steam shortcut");
        }
        await appDetailsCache.FetchDataForApp(id)
        await appDetailsStore.RequestAppDetails(id);
        SteamClient.Apps.SetShortcutName(id, (gameData.Content as GameDetails).Name);
        return id;
    };

    return (
        <div className={gameDetailsRootClass}>
            <style>
                {`
                .${gameDetailsRootClass} .GenericConfirmDialog {
                    width: 100%;
                    height: 100%;
                    padding: 0;
                    border: 0;
                    border-radius: 0;
                    background: #0e172175;
                    backdrop-filter: blur(8px);
                }
                .${gameDetailsRootClass} .${gamepadDialogClasses.ModalPosition} {
                    padding: 0;
                }
                .${footerClasses.BasicFooter} {
                    border-top: unset;
                }
                @keyframes fadeIn {
                    from {
                        opacity: 0;
                    }
                    to {
                        opacity: 1;
                    }
                }
            `}
            </style>
            <ModalRoot onCancel={closeModal}>
                <Focusable
                    style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
                    onCancelActionDescription="Go back to Store"
                >
                    {gameData.Type === "Empty" && <Loading />}
                    {gameData.Type === "GameDetails" &&
                        <GameDisplay
                            name={(gameData.Content as GameDetails).Name}
                            shortName={(gameData.Content as GameDetails).ShortName}
                            description={(gameData.Content as GameDetails).Description}
                            images={(gameData.Content as GameDetails).Images}
                            steamClientID={steamClientID}
                            closeModal={closeModal}
                            installing={installing}
                            installer={() => download(false)}
                            progress={progress}
                            cancelInstall={cancelInstall}
                            uninstaller={uninstall}
                            editors={(gameData.Content as GameDetails).Editors}
                            initActionSet={initActionSet}
                            runner={() => {
                                closeModal && closeModal();
                                const rid = parseInt(steamClientID, 10);
                            if (!Number.isNaN(rid)) runApp(rid, onExeExit)
                            }}
                            actions={scriptActions}
                            resetLaunchOptions={resetLaunchOptions}
                            updater={() => download(true)}
                            scriptRunner={runScript}
                            reloadData={reloadData}
                            onExeExit={onExeExit}
                            queueItem={queueItem}
                        />
                    }
                </Focusable>
            </ModalRoot >
        </div>
    );
};
