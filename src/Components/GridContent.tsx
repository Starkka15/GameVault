import { DialogButton, Focusable, Menu, MenuItem, Navigation, ProgressBar, ServerAPI, Spinner, TextField, gamepadTabbedPageClasses, showContextMenu, showModal } from "decky-frontend-lib";
import { ContentResult, ContentType, ExecuteArgs, ExecuteGetGameDetailsArgs, GameData, GameDataList, GameImages, MenuAction, ScriptActions } from "../Types/Types";
import { Dispatch, SetStateAction, VFC, memo, useEffect, useRef, useState } from "react";
import GameGridItem from './GameGridItem';
import { GameDetailsItem } from './GameDetailsItem';
import Logger from "../Utils/logger";
import { FaSlidersH, FaCog, FaRegCheckCircle } from 'react-icons/fa';
import { LoginContent } from './LoginContent';
import { executeAction } from '../Utils/executeAction';
import { ConfEditor } from '../ConfEditor';
import { FaStore } from "react-icons/fa6";
import { installQueue, QueueState } from '../Utils/installQueue';

export const contentTabsContainerClass = 'content-tabs-container';
export const gridContentContainerClass = 'grid-content-container';

interface GridContentArgs {
    filter?: string;
    installed?: boolean;
    limited?: boolean;
}

interface GridContentCache {
    filter: string;
    installed: boolean;
}

interface GridContentProps {
    content: GameDataList;
    serverAPI: ServerAPI;
    initActionSet: string;
    refreshContent: (actionArgs: GridContentArgs, onFinish?: () => void) => void;
    argsCache: GridContentCache;
    setArgsCache: Dispatch<SetStateAction<GridContentCache>>;
}

export const GridContent: VFC<GridContentProps> = ({ content, serverAPI, initActionSet, refreshContent, argsCache, setArgsCache }) => {
    const logger = new Logger('ContentGrid');
    const [isLimited, setIsLimited] = useState(true);
    const [isLimitedLoading, setIsLimitedLoading] = useState(false);
    const [installedFilterLoading, setInstalledLoading] = useState(false);
    const [scriptActions, setScriptActions] = useState<MenuAction[] | null>();
    const [filter, setFilter] = useState(argsCache.filter);
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [selectMode, setSelectMode] = useState(false);
    const [selectedGames, setSelectedGames] = useState<Set<string>>(new Set());
    const [queueState, setQueueState] = useState<QueueState>(installQueue.getState());
    const [artworkBusy, setArtworkBusy] = useState(false);

    useEffect(() => {
        installQueue.setServerAPI(serverAPI);
        const unsub = installQueue.subscribe(setQueueState);
        return () => {
            unsub();
            if (debounceRef.current) clearTimeout(debounceRef.current);
        };
    }, [serverAPI]);

    const toggleSelection = (game: GameData) => {
        // Only allow selecting uninstalled games
        if (game.SteamClientID) return;
        setSelectedGames(prev => {
            const next = new Set(prev);
            if (next.has(game.ShortName)) next.delete(game.ShortName);
            else next.add(game.ShortName);
            return next;
        });
    };

    const startBatchInstall = () => {
        const games = content.Games?.filter(g => selectedGames.has(g.ShortName)) ?? [];
        games.forEach(g => installQueue.add(g.ShortName, g.Name, initActionSet));
        setSelectMode(false);
        setSelectedGames(new Set());
        installQueue.start();
    };

    useEffect(() => {
        (async () => {
            try {
                const actionRes = await executeAction<ExecuteArgs, ScriptActions>(serverAPI, initActionSet, "GetScriptActions", {});
                logger.debug('Get sscript actions result', actionRes);
                if (!actionRes) {
                    return;
                }
                const scriptActions = actionRes.Content;
                setScriptActions(scriptActions.Actions);
            }
            catch (e) {
                logger.error(e);
            }
        })();
    }, []);

    // Bulk artwork: for every added game (has a Steam shortcut) in the current list,
    // fetch SteamGridDB art by title (name-guarded in the backend) and apply it to the
    // shortcut. Games with no confident SGDB match / no uploaded art are simply skipped.
    const fetchAllArtwork = async () => {
        if (artworkBusy) return;
        const games = (content.Games ?? []).filter(g => g.SteamClientID);
        if (games.length === 0) {
            serverAPI.toaster.toast({ title: "GameVault", body: "No added games in view to fetch artwork for." });
            return;
        }
        setArtworkBusy(true);
        serverAPI.toaster.toast({ title: "GameVault", body: `Fetching artwork for ${games.length} game(s)…` });
        let applied = 0;
        for (const g of games) {
            const id = parseInt(g.SteamClientID, 10);
            if (Number.isNaN(id)) continue;
            try {
                const imageResult = await executeAction<ExecuteGetGameDetailsArgs, GameImages>(
                    serverAPI, initActionSet, "GetJsonImages", { shortname: g.ShortName });
                const images = imageResult?.Content;
                if (!images) continue;
                let any = false;
                if (images.Grid) { await SteamClient.Apps.SetCustomArtworkForApp(id, images.Grid, 'png', 0); any = true; }
                if (images.Hero) { await SteamClient.Apps.SetCustomArtworkForApp(id, images.Hero, 'png', 1); any = true; }
                if (images.Logo) { await SteamClient.Apps.SetCustomArtworkForApp(id, images.Logo, 'png', 2); any = true; }
                if (images.GridH) { await SteamClient.Apps.SetCustomArtworkForApp(id, images.GridH, 'png', 3); any = true; }
                if (any) applied++;
            } catch (e) {
                logger.error(`artwork fetch failed for ${g.Name}`, e);
            }
        }
        setArtworkBusy(false);
        serverAPI.toaster.toast({ title: "GameVault", body: `Artwork applied to ${applied}/${games.length} game(s).` });
    };

    const actionsMenu = (e: any) => {
        showContextMenu(
            <Menu label="Actions" cancelText="Cancel" onCancel={() => { }}>
                <MenuItem disabled={artworkBusy} onSelected={fetchAllArtwork}>
                    {artworkBusy ? "Fetching Artwork…" : "Fetch Artwork (SteamGridDB)"}
                </MenuItem>
                {scriptActions?.map((action) =>
                    <MenuItem
                        onSelected={async () => {
                            const args = {
                                shortname: "",
                                steamClientID: "",
                                startDir: "",
                                compatToolName: "",
                                inputData: "",
                                gameId: "",
                                appId: ""
                            };
                            const result = await executeAction<ExecuteArgs, ContentResult<ContentType>>(serverAPI, initActionSet, action.ActionId, args);
                            if (result?.Type == "RefreshContent") {
                                refreshContent({ ...argsCache, limited: isLimited });
                            }
                            logger.debug("runScript result", result);
                        }}
                    >
                        {action.Title}
                    </MenuItem>
                )}
            </Menu>,
            e.currentTarget ?? window
        );
    };

    const updateCache: <Param extends keyof GridContentArgs>(param: Param, value: GridContentArgs[Param], onFinish?: () => void) => void =
        (param, value, onFinish) => {
            const newCache = { ...argsCache, [param]: value };
            refreshContent({ ...newCache, limited: isLimited }, () => {
                setArgsCache(newCache);
                onFinish?.();
            });
        };

    return (
        <Focusable
            className={gridContentContainerClass}
            onSecondaryButton={() => {
                setInstalledLoading(true);
                updateCache('installed', !argsCache.installed, () => setInstalledLoading(false));
            }}
            onOptionsButton={() => {
                setIsLimitedLoading(true);
                refreshContent({ ...argsCache, limited: !isLimited }, () => {
                    setIsLimited(!isLimited);
                    setIsLimitedLoading(false);
                });
            }}
            onSecondaryActionDescription={
                <div style={{ display: 'flex', gap: '4px' }}>
                    <text>Toggle Installed</text>
                    {argsCache.installed && <FaRegCheckCircle style={{ alignSelf: 'center' }} size='14px' />}
                    {installedFilterLoading && <Spinner style={{ width: '20px' }} />}
                </div>
            }
            onOptionsActionDescription={
                <div style={{ display: 'flex', gap: '4px' }}>
                    <text>{isLimited ? 'Show All' : 'Limit Results'}</text>
                    {isLimitedLoading && <Spinner style={{ width: '20px' }} />}
                </div>
            }
        >
            <style>{`
                .${contentTabsContainerClass} .${gamepadTabbedPageClasses.TabContentsScroll} {
                    scroll-padding-top: calc( var(--basicui-header-height) + 140px ) !important;
                    scroll-padding-bottom: 80px;
                }
                .${contentTabsContainerClass} .${gamepadTabbedPageClasses.TabContents} .${gridContentContainerClass} {
                    padding-top: 15px;
                }
            `}</style>
            <Focusable style={{ display: "flex", gap: '15px' }}>
                <div style={{ width: '100%' }}>
                    <TextField
                        placeholder="Search"
                        value={filter}
                        onChange={(e) => {
                            const val = e.target.value;
                            setFilter(val);
                            if (debounceRef.current) clearTimeout(debounceRef.current);
                            debounceRef.current = setTimeout(() => updateCache('filter', val), 400);
                        }}
                    />
                </div>
                <DialogButton
                    onClick={actionsMenu}
                    disabled={!scriptActions}
                    style={{ width: "48px", minWidth: 'initial', padding: 'initial' }}
                >
                    <FaSlidersH style={{ verticalAlign: 'middle' }} />
                </DialogButton>
                <DialogButton
                    onClick={() => showModal(
                        <ConfEditor
                            serverAPI={serverAPI}
                            initActionSet={initActionSet}
                            initAction="GetTabConfigActions"
                            contentId="0"
                            refreshParent={() => refreshContent({ ...argsCache, limited: isLimited })}
                        />
                    )}
                    style={{ width: "48px", minWidth: 'initial', padding: 'initial' }}
                >
                    <FaCog style={{ verticalAlign: 'middle' }} />
                </DialogButton>
                {content.storeURL &&
                    <DialogButton
                        onClick={() => {
                            if(content.storeURL)
                                Navigation.NavigateToExternalWeb(content.storeURL);
                        }}
                        style={{ width: "48px", minWidth: 'initial', padding: 'initial' }}>
                        <FaStore />
                    </DialogButton>}
                <DialogButton
                    onClick={() => {
                        setSelectMode(!selectMode);
                        if (selectMode) setSelectedGames(new Set());
                    }}
                    style={{
                        width: "48px", minWidth: 'initial', padding: 'initial',
                        ...(selectMode ? { backgroundColor: '#1a9fff' } : {})
                    }}
                >
                    <FaRegCheckCircle style={{ verticalAlign: 'middle' }} />
                </DialogButton>
            </Focusable>
            {selectMode && selectedGames.size > 0 && (
                <div style={{ display: 'flex', gap: '10px', marginTop: '8px', alignItems: 'center' }}>
                    <DialogButton onClick={startBatchInstall} style={{ flex: 1 }}>
                        Install Selected ({selectedGames.size})
                    </DialogButton>
                    <DialogButton onClick={() => setSelectedGames(new Set())}
                        style={{ width: "120px", minWidth: 'initial' }}>
                        Clear
                    </DialogButton>
                </div>
            )}
            {queueState.isProcessing && (() => {
                const current = queueState.items.find(i => i.status === 'downloading' || i.status === 'installing');
                const queuedCount = queueState.items.filter(i => i.status === 'queued').length;
                if (!current) return null;
                return (
                    <Focusable
                        onActivate={() => Navigation.Navigate('/gamevault-downloads')}
                        onOKActionDescription="View Downloads"
                        noFocusRing={true}
                        style={{
                            marginTop: '8px', padding: '8px 12px',
                            backgroundColor: '#1a1a2e', borderRadius: '8px',
                            border: '1px solid #2a2a4a', cursor: 'pointer',
                        }}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                            <span style={{ fontSize: '12px', color: '#b0b0b0' }}>
                                {current.title} — {current.description}
                            </span>
                            {queuedCount > 0 && (
                                <span style={{ fontSize: '11px', color: '#1a9fff' }}>
                                    +{queuedCount} queued
                                </span>
                            )}
                        </div>
                        <ProgressBar nProgress={current.progress} />
                    </Focusable>
                );
            })()}
            {content.NeedsLogin === "true" && (
                <div style={{ paddingTop: '15px' }}>
                    <LoginContent serverAPI={serverAPI} initActionSet={initActionSet} initAction="GetLoginActions" />
                </div>
            )}
            {argsCache.installed && (
                <div style={{ margin: '8px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '5px' }}>
                    <div style={{ backgroundColor: '#8b929a66', flex: 'auto', height: '1px' }} />
                    <div style={{ color: '#ffffffb3', fontSize: '12px', textTransform: 'uppercase' }}>
                        Installed
                    </div>
                    <div style={{ backgroundColor: '#8b929a66', flex: 'auto', height: '1px' }} />
                </div>
            )}
            {content.Games?.length === 0 && (
                <div style={{ textAlign: 'center', padding: '15px' }}>
                   
                    {argsCache.filter !== "" && (
                        <div>
                            No games match the filter: {argsCache.filter}. Clear the search bar.
                        </div>
                    )}
                    {argsCache.installed && (
                        <div>
                            No installed games. Push X to toggle installed games off.
                        </div>
                    )}
                </div>   
            )}
            <GridItems
                serverAPI={serverAPI}
                games={content.Games ?? []}
                initActionSet={initActionSet}
                initAction=""
                selectMode={selectMode}
                selectedGames={selectedGames}
                onToggleSelect={toggleSelection}
            />
        </Focusable>
    );
};

interface GridItemsProperties {
    games: GameData[];
    serverAPI: ServerAPI;
    initActionSet: string;
    initAction: string;
    selectMode?: boolean;
    selectedGames?: Set<string>;
    onToggleSelect?: (game: GameData) => void;
}

const GridItems: VFC<GridItemsProperties> = memo(({ serverAPI, games, initActionSet, initAction, selectMode, selectedGames, onToggleSelect }) => {
    const logger = new Logger("GridContainer");

    const imgAreaWidth = '120px';
    const imgAreaHeight = '165px';

    return (
        <>
            <Focusable
                style={{
                    display: "grid",
                    justifyContent: "space-between",
                    gridGap: "16px 12px",
                    gridTemplateColumns: `repeat(auto-fill, ${imgAreaWidth})`,
                    marginTop: '15px'
                }}
                //@ts-ignore
                navEntryPreferPosition={2} //maintain x
            >
                {games.map((game: GameData) => (
                    <GameGridItem
                        gameData={game}
                        imgAreaWidth={imgAreaWidth}
                        imgAreaHeight={imgAreaHeight}
                        selectMode={selectMode && !game.SteamClientID}
                        isSelected={selectedGames?.has(game.ShortName)}
                        onClick={() => {
                            if (selectMode && !game.SteamClientID && onToggleSelect) {
                                onToggleSelect(game);
                            } else {
                                logger.debug("onClick game: ", game);
                                showModal(
                                    <GameDetailsItem
                                        serverAPI={serverAPI}
                                        shortname={game.ShortName}
                                        initActionSet={initActionSet}
                                        initAction={initAction}
                                        clearActiveGame={() => { }}
                                    />
                                );
                            }
                        }}
                    />
                ))}
            </Focusable>
        </>
    );
});
