import { ConfirmModal, DialogBody, DialogButton, DialogControlsSection, Field, Focusable, Navigation, PanelSection, ServerAPI, SidebarNavigation, TextField, ToggleField, showModal } from "decky-frontend-lib";
import { VFC, useEffect, useRef, useState } from "react";
import { HiOutlineQrCode } from "react-icons/hi2";
import { SiDiscord, SiGithub } from "react-icons/si";
import { showQrModal } from "./MainMenu";
import Logger, { log } from "./Utils/logger";
import { LogViewer } from "./LogViewer";
import { ScrollableWindowRelative } from './ScrollableWindow';
import { Developer } from "./Developer";
import { addAchievement, checkAchievements, hasAchievement, hasAchievements } from "./Utils/achievements";
import { Achievements } from "./Achievements";
import { FaInfo, FaQ, FaQuestion } from "react-icons/fa6";
import { StorageTab } from "./StorageTab";

declare const __PLUGIN_VERSION__: string;

export const About: VFC<{ serverAPI: ServerAPI; }> = ({ serverAPI }) => {
    const [url, setUrl] = useState("");
    const [backup, setBackup] = useState("false");
    const [reloading, setReloading] = useState(false);
    const logger = new Logger("About");
    const [output, setOutput] = useState("");
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const socket = useRef<WebSocket | null>(null);
    const [isInstalling, setIsInstalling] = useState(false);
    const [isDownloading, setIsDownloading] = useState(false);
    const [isDeveloperMode, setIsDeveloperMode] = useState(localStorage.getItem('gv_developermode') === "true");
    const [updateInfo, setUpdateInfo] = useState<any>(null);
    const [updateChecking, setUpdateChecking] = useState(false);
    const [updateOutput, setUpdateOutput] = useState("");
    const [isUpdating, setIsUpdating] = useState(false);
    const isUpdatingRef = useRef(false);
    const updateTextareaRef = useRef<HTMLTextAreaElement>(null);
    const [sudoPassword, setSudoPassword] = useState("");

    const showDeveloperMode = (show: boolean) => {
        setIsDeveloperMode(show)
        localStorage.setItem('gv_developermode', show.toString())
        if (show)
            addAchievement('MTA=')
    }

    const download = async () => {
        console.log("Download: ", url);
        setIsDownloading(true);
        await serverAPI.callPluginMethod("download_custom_backend", {
            url: url,
            backup: backup
        });
        await serverAPI.callPluginMethod("reload", {})
        setIsDownloading(false);
        addAchievement('MTAw')
    };
    const socialLinks = [
        {
            label: "GitHub",
            icon: <SiGithub />,
            link: "https://github.com/Starkka15/junkstore",
            buttonText: "Report Issues",
        },
        {
            label: "Original Project Discord",
            icon: <SiDiscord />,
            link: "https://discord.gg/uqemZ6cfHe",
            buttonText: "Join",
        },
    ];
    // Wire a fresh WebSocket's handlers. Kept separate so we can reconnect on demand
    // (the socket can be CLOSED by the time the user clicks a long-lived button).
    const wireSocket = (ws: WebSocket) => {
        ws.onmessage = (event) => {
            logger.debug("Received message: " + event.data);
            const message = JSON.parse(event.data)
            if (isUpdatingRef.current) {
                setUpdateOutput((prev) => prev + message.data + "\n");
                if (updateTextareaRef.current !== null) {
                    updateTextareaRef.current.scrollTop = updateTextareaRef.current.scrollHeight;
                }
                if (message.status === "closed") {
                    setIsUpdating(false);
                    isUpdatingRef.current = false;
                }
            } else {
                setOutput((prevOutput) => prevOutput + message.data + "\n");
                if (textareaRef.current !== null) {
                    textareaRef.current.scrollTop = textareaRef.current.scrollHeight;
                }
                if (message.status === "closed") {
                    setIsInstalling(false)
                }
            }
        };
    };

    // Open (or reopen) the socket and resolve once it is OPEN. Rejects on error.
    const connectSocket = (): Promise<WebSocket> => {
        return new Promise((resolve, reject) => {
            const existing = socket.current;
            if (existing && existing.readyState === WebSocket.OPEN) {
                resolve(existing);
                return;
            }
            serverAPI.callPluginMethod<{}, Number>("get_websocket_port", {}).then((port) => {
                const address = "ws://localhost:" + port.result + "/ws";
                logger.debug("Connecting to WebSocket: " + address);
                const ws = new WebSocket(address);
                socket.current = ws;
                wireSocket(ws);
                ws.onopen = () => resolve(ws);
                ws.onerror = () => reject(new Error("WebSocket connection failed"));
            }).catch(reject);
        });
    };

    // Send an action, guaranteeing the socket is OPEN first. On failure, report it
    // to the given output sink so the UI never hangs silently.
    const sendAction = async (payload: object, reportErr: (msg: string) => void) => {
        try {
            const ws = await connectSocket();
            ws.send(JSON.stringify(payload));
        } catch (e) {
            const msg = "ERROR: could not reach the backend (" + String(e) + "). Try reopening this page.";
            logger.error(msg);
            reportErr(msg + "\n");
            setIsUpdating(false);
            isUpdatingRef.current = false;
            setIsInstalling(false);
        }
    };

    useEffect(() => {
        connectSocket().catch((e) => logger.error("initial WS connect failed: " + String(e)));
        // Clean up the WebSocket connection
        return () => {
            if (socket.current) {
                socket.current.close();
            }
        };
    }, []);
    const getRuntimeId = (name: string) => {
        // @ts-ignore
        const app = appStore.allApps.filter(a => a.display_name.startsWith(name))
        if (app.length === 0) {
            return -1
        }
        else
            return app[0].appid
    }

    const isRuntimeInstalled = (name: string) => {

        // @ts-ignore
        return appStore.GetAppOverviewByAppID(getRuntimeId(name)).local_per_client_data.installed

    }

    return (
        <DialogBody>
            <DialogControlsSection style={{ height: "calc(100%)" }}>
                <SidebarNavigation key="1" pages={[
                    {
                        title: "About",
                        content: (
                            <div style={{ padding: '0 15px', height: '100%', display: 'flex' }}>
                                <ScrollableWindowRelative>
                                    <div style={{ padding: '5px 0' }}>
                                        <div>
                                            <h2>GameVault</h2>
                                            <span style={{ fontSize: "14px", color: "#8b929a" }}>v{__PLUGIN_VERSION__}</span>
                                            <br />
                                            An open and extensible multi-store game launcher for Steam Deck. Access Epic, GOG, Amazon, and itch.io games directly from Game Mode.
                                            <br />
                                            <br />
                                            This is a community fork of <a href="https://github.com/ebenbruyns/junkstore">Junk-Store</a> by Eben Bruyns, with additional store integrations and features.
                                            <br />
                                            <br />
                                            Please note: Before diving in, make sure to install the listed dependencies from the 'Dependencies' tab.
                                            <br />
                                            <br />
                                            <h2>Original Project Contributors</h2>
                                            <ul>
                                                <li>Eben Bruyns (junkrunner) - Software Sorcerer</li>
                                                <li>Annie Ryan (mrs junkrunner) - Order Oracle</li>
                                                <li>Jesse Bofill - Visual Virtuoso</li>
                                                <li>Tech - Glitch Gladiator</li>
                                                <li>Logan (Beebles) - UI Developer</li>
                                            </ul>
                                            <h2>Community Fork</h2>
                                            <ul>
                                                <li>Starkka15 - GOG, Amazon, itch.io extensions, cloud save sync, SteamGridDB</li>
                                            </ul>
                                        </div>
                                    </div>
                                    <ToggleField
                                        label="Enable Developer Mode"
                                        checked={isDeveloperMode}
                                        onChange={(newValue) => showDeveloperMode(newValue)}

                                    />
                                </ScrollableWindowRelative>
                            </div>
                        )
                    },
                    {
                        title: "Storage",
                        content: <StorageTab serverAPI={serverAPI} />
                    },
                    {
                        title: "Updates",
                        content: (
                            <div style={{ padding: '0 15px', height: '100%', display: 'flex' }}>
                                <ScrollableWindowRelative>
                                    <PanelSection>
                                        <div style={{ marginBottom: "10px" }}>
                                            <span style={{ fontSize: "14px", color: "#8b929a" }}>
                                                Current version: v{__PLUGIN_VERSION__}
                                            </span>
                                        </div>
                                        <DialogButton
                                            disabled={updateChecking || isUpdating}
                                            onClick={async () => {
                                                setUpdateChecking(true);
                                                setUpdateInfo(null);
                                                try {
                                                    const result = await serverAPI.callPluginMethod<{}, any>("check_for_update", {});
                                                    logger.debug("check_for_update result: " + JSON.stringify(result));
                                                    if (result.success) {
                                                        const data = result.result;
                                                        if (data?.Type === "UpdateCheck") {
                                                            setUpdateInfo(data.Content);
                                                        } else if (data?.Type === "Error") {
                                                            setUpdateInfo({ error: data.Content?.Message || "Unknown backend error" });
                                                        } else {
                                                            setUpdateInfo({ error: "Unexpected response: " + JSON.stringify(data) });
                                                        }
                                                    } else {
                                                        setUpdateInfo({ error: "Plugin call failed: " + String(result.result) });
                                                    }
                                                } catch (e) {
                                                    setUpdateInfo({ error: String(e) });
                                                }
                                                setUpdateChecking(false);
                                            }}
                                        >
                                            {updateChecking ? "Checking..." : "Check for Updates"}
                                        </DialogButton>
                                    </PanelSection>

                                    {updateInfo && !updateInfo.error && (
                                        <PanelSection>
                                            {updateInfo.update_available ? (
                                                <div>
                                                    <div style={{ marginBottom: "8px" }}>
                                                        <strong>Update available: v{updateInfo.latest_version}</strong>
                                                    </div>
                                                    {updateInfo.release_name && (
                                                        <div style={{ marginBottom: "4px", fontSize: "14px" }}>
                                                            {updateInfo.release_name}
                                                        </div>
                                                    )}
                                                    {updateInfo.release_body && (
                                                        <div style={{
                                                            marginBottom: "10px",
                                                            fontSize: "13px",
                                                            color: "#b8bcbf",
                                                            whiteSpace: "pre-wrap",
                                                            maxHeight: "200px",
                                                            overflowY: "auto",
                                                            padding: "8px",
                                                            background: "rgba(0,0,0,0.2)",
                                                            borderRadius: "4px",
                                                        }}>
                                                            {updateInfo.release_body}
                                                        </div>
                                                    )}
                                                    <div style={{ marginBottom: "8px" }}>
                                                        <TextField
                                                            bIsPassword={true}
                                                            placeholder="Sudo password (leave blank if none)"
                                                            value={sudoPassword}
                                                            onChange={(e) => setSudoPassword(e.target.value)}
                                                        />
                                                    </div>
                                                    <DialogButton
                                                        disabled={isUpdating}
                                                        onClick={() => {
                                                            showModal(
                                                                <ConfirmModal
                                                                    strTitle="Install Update"
                                                                    strDescription={`Update to v${updateInfo.latest_version}? This will restart Decky Loader.`}
                                                                    onOK={() => {
                                                                        setUpdateOutput("Connecting to backend...\n");
                                                                        setIsUpdating(true);
                                                                        isUpdatingRef.current = true;
                                                                        sendAction({
                                                                            action: "self_update",
                                                                            download_url: updateInfo.download_url,
                                                                            sudo_password: sudoPassword,
                                                                        }, (m) => setUpdateOutput((prev) => prev + m));
                                                                    }}
                                                                />
                                                            );
                                                        }}
                                                    >
                                                        {isUpdating ? "Updating... Do not close this screen." : "Install Update"}
                                                    </DialogButton>
                                                </div>
                                            ) : (
                                                <div style={{ color: "#8b929a" }}>
                                                    You are running the latest version (v{updateInfo.current_version}).
                                                </div>
                                            )}
                                        </PanelSection>
                                    )}

                                    {updateInfo?.error && (
                                        <PanelSection>
                                            <div style={{ color: "#d94141" }}>
                                                Error: {updateInfo.error}
                                            </div>
                                        </PanelSection>
                                    )}

                                    {(isUpdating || updateOutput) && (
                                        <PanelSection>
                                            <textarea
                                                ref={updateTextareaRef}
                                                style={{ width: "100%", height: "200px", marginTop: "10px" }}
                                                value={updateOutput}
                                                readOnly
                                            />
                                        </PanelSection>
                                    )}
                                </ScrollableWindowRelative>
                            </div>
                        )
                    },
                    {
                        title: "Dependencies",
                        content: <>


                            <PanelSection>


                                <DialogButton
                                    disabled={isInstalling}
                                    onClick={async () => {
                                        logger.debug("Sending message: install_dependencies");
                                        setOutput("Connecting to backend...\n");
                                        setIsInstalling(true);
                                        await sendAction({ action: "install_dependencies" }, (m) => setOutput((prev) => prev + m));
                                    }}
                                >
                                    {isInstalling ? "Working... Do not close this screen." : "Install Dependencies"}
                                </DialogButton>
                                <textarea
                                    ref={textareaRef}
                                    style={{ width: "100%", height: "200px", marginTop: "10px" }}
                                    value={output}
                                />
                            </PanelSection>
                            <PanelSection>
                                <DialogButton
                                    disabled={reloading}
                                    onClick={async () => {
                                        setReloading(true);
                                        await serverAPI.callPluginMethod("reload", {})
                                        setReloading(false);
                                    }}>
                                    {reloading == true ? "Reloading Scripts..." : "Reload scripts"}
                                </DialogButton>
                            </PanelSection>
                            <PanelSection>
                                <DialogButton
                                    disabled={isRuntimeInstalled("Proton EasyAntiCheat Runtime")}
                                    onClick={async () => {
                                        SteamClient.Installs.OpenInstallWizard([getRuntimeId("Proton EasyAntiCheat Runtime")]);
                                    }
                                    }>Install Proton Easy Anti Cheat</DialogButton>

                            </PanelSection>

                            <PanelSection>
                                <DialogButton
                                    disabled={isRuntimeInstalled("Proton BattlEye Runtime")}
                                    onClick={async () => {
                                        SteamClient.Installs.OpenInstallWizard([getRuntimeId("Proton BattlEye Runtime")]);
                                    }
                                    }>Install Proton BattlEye Runtime</DialogButton>
                            </PanelSection>

                            <PanelSection>
                                <DialogButton
                                    disabled={isInstalling}
                                    onClick={async () => {
                                        logger.debug("Sending message: install_ge_proton");
                                        setOutput("Connecting to backend...\n");
                                        setIsInstalling(true);
                                        await sendAction({ action: "install_ge_proton" }, (m) => setOutput((prev) => prev + m));
                                    }}
                                >
                                    {isInstalling ? "Installing GE-Proton... Do not close this screen." : "Install Latest GE-Proton"}
                                </DialogButton>
                            </PanelSection>

                            <PanelSection>

                                <DialogButton
                                    disabled={isInstalling}
                                    onClick={() => showModal(<ConfirmModal strTitle="Confirm" strDescription={"Uninstall dependencies?"} onOK={
                                        async () => {
                                            logger.debug("Sending message: uninstall_dependencies");
                                            setOutput("Connecting to backend...\n");
                                            setIsInstalling(true);
                                            await sendAction({ action: "uninstall_dependencies" }, (m) => setOutput((prev) => prev + m));
                                        }} />)}

                                >
                                    {isInstalling ? "Working... Do not close this screen." : "Uninstall Dependencies"}
                                </DialogButton>
                            </PanelSection>
                            {!hasAchievement("MTEx") &&
                                <PanelSection>
                                    <DialogButton
                                        onClick={() => {
                                            addAchievement("MTEx")
                                            showModal(<ConfirmModal strTitle="Do you feel luck?" strDescription="I told you not to click this button!" strOKButtonText="Yes"
                                                onOK={() => {
                                                    if (!hasAchievement("MTAwMA=="))
                                                        addAchievement("MTAwMQ==")
                                                }} strCancelButtonText="No"
                                                onCancel={() => {
                                                    if (!hasAchievement("MTAwMQ=="))
                                                        addAchievement("MTAwMA==")
                                                }} />)
                                        }}>
                                        Do NOT click this Button!
                                    </DialogButton>
                                </PanelSection>
                            }
                        </>
                    },
                    {
                        title: "Custom Backend",
                        content: <><PanelSection>
                            <div>GameVault is a flexible and extensible frontend. You can use a custom backend to provide the content for the store.
                                This does come with security concerns so beware of what you download. You can create your own custom backends too by following
                                the instructions on github.
                                <br />
                                <br />
                                <DialogButton onClick={() => {
                                    Navigation.NavigateToExternalWeb("https://github.com/ebenbruyns/junkstore/wiki/Custom-Backends");
                                }
                                }>Learn More</DialogButton>
                            </div>
                            <br />
                        </PanelSection>
                            <PanelSection>
                                <TextField placeholder="Enter URL" value={url} onChange={(e) => setUrl(e.target.value)} />
                            </PanelSection>
                            <PanelSection> <ToggleField label="Backup" checked={backup === "true"}
                                onChange={(newValue) => setBackup(newValue.toString())} />
                            </PanelSection>
                            <PanelSection>
                                <DialogButton
                                    disabled={isDownloading}
                                    onClick={download}>{isDownloading ? "Downloading..." : "Download"} </DialogButton>
                            </PanelSection>
                        </>
                    },
                    {
                        title: "Links",
                        content: <Focusable style={{ display: "flex", flexDirection: "column" }}>
                            {socialLinks.map((linkInfo, index) => (
                                <Field
                                    key={index}
                                    label={linkInfo.label}
                                    icon={linkInfo.icon}
                                    bottomSeparator={"none"}
                                    padding={"none"}
                                    indentLevel={1}
                                >
                                    <Focusable
                                        style={{
                                            marginLeft: "auto",
                                            boxShadow: "none",
                                            display: "flex",
                                            justifyContent: "right",
                                            padding: "4px",
                                        }}
                                    >
                                        <DialogButton
                                            onClick={() => {
                                                Navigation.NavigateToExternalWeb(linkInfo.link);
                                                addAchievement("MTAxMA==")
                                            }}
                                            style={{
                                                padding: "10px",
                                                fontSize: "14px",
                                            }}
                                        >
                                            {linkInfo.buttonText}
                                        </DialogButton>
                                        <DialogButton
                                            onClick={() => {
                                                showQrModal(linkInfo.link);
                                            }}
                                            style={{
                                                display: "flex",
                                                justifyContent: "center",
                                                alignItems: "center",
                                                padding: "10px",
                                                maxWidth: "40px",
                                                minWidth: "auto",
                                                marginLeft: ".5em",
                                            }}
                                        >
                                            <HiOutlineQrCode />
                                        </DialogButton>
                                    </Focusable>
                                </Field>
                            ))}
                        </Focusable>
                    },


                    {
                        title: "Logs",
                        content: <LogViewer serverAPI={serverAPI}></LogViewer>
                    },
                    {
                        title: "Achievements",
                        visible: hasAchievements(),
                        content:
                            <Achievements serverAPI={serverAPI} />

                    },
                    {
                        title: "Developer",
                        visible: isDeveloperMode,
                        content: <div>
                            <Developer serverAPI={serverAPI} />
                        </div>
                    }
                ]}

                    showTitle

                />
            </DialogControlsSection >
        </DialogBody >
    );
};
