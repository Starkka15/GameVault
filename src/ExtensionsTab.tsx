import { ConfirmModal, DialogButton, Field, Focusable, PanelSection, SteamSpinner, showModal } from "@decky/ui";
import { call } from "@decky/api";
import { FC, useEffect, useRef, useState } from "react";
import { ScrollableWindowRelative } from "./ScrollableWindow";
import { clearContentCache } from "./ContentTabs";
import { ExtensionItem, ExtensionsInfo, getExtensions, relinkExtension } from "./Utils/extensions";
import Logger from "./Utils/logger";

/**
 * Pick which stores GameVault shows. Epic, GOG and Amazon are built in; the rest
 * come from the GameVault-Extensions catalog and can be installed, updated and
 * removed here. Removing one keeps its login and library on the device, so
 * installing it again picks up where it left off.
 */
export const ExtensionsTab: FC = () => {
    const logger = new Logger("ExtensionsTab");
    const [info, setInfo] = useState<ExtensionsInfo | null>(null);
    const [loadError, setLoadError] = useState("");
    const [busy, setBusy] = useState<string | null>(null);
    const [output, setOutput] = useState("");
    const outputRef = useRef<HTMLTextAreaElement>(null);
    const socket = useRef<WebSocket | null>(null);

    const load = async () => {
        setLoadError("");
        try {
            setInfo(await getExtensions());
        } catch (e) {
            setLoadError(String(e));
        }
    };

    useEffect(() => {
        load();
        return () => socket.current?.close();
    }, []);

    const append = (text: string) => {
        setOutput(prev => prev + text);
        setTimeout(() => {
            if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
        }, 0);
    };

    const run = async (action: "install_extension" | "remove_extension", item: ExtensionItem, profile = false) => {
        setBusy(item.id);
        setOutput("");
        try {
            const port = await call<[], number>("get_websocket_port");
            const ws = new WebSocket(`ws://localhost:${port}/ws`);
            socket.current = ws;
            ws.onmessage = async (event) => {
                const msg = JSON.parse(event.data);
                if (msg.data) append(msg.data);
                if (msg.status !== "closed") return;
                ws.close();
                if (Array.isArray(msg.removedApps) && msg.removedApps.length) {
                    for (const appId of msg.removedApps) {
                        try { SteamClient.Apps.RemoveShortcut(appId); }
                        catch (e) { logger.error(`RemoveShortcut ${appId}: ${e}`); }
                    }
                    append(`Removed ${msg.removedApps.length} Steam shortcut(s).\n`);
                }
                if (msg.ok && msg.relink) {
                    const n = await relinkExtension(item.id);
                    if (n) append(`Updated ${n} game shortcut(s).\n`);
                }
                clearContentCache();
                setBusy(null);
                await load();
            };
            ws.onerror = () => {
                append("ERROR: could not reach the GameVault backend.\n");
                setBusy(null);
            };
            ws.onopen = () => ws.send(JSON.stringify({ action, id: item.id, profile }));
        } catch (e) {
            logger.error(e);
            append(`ERROR: ${e}\n`);
            setBusy(null);
        }
    };

    const confirmRemove = (item: ExtensionItem) => {
        showModal(
            <ConfirmModal
                strTitle={`Remove ${item.name}?`}
                strDescription={
                    <div>
                        <p><b>Extension only:</b> its tab goes away and its games won't launch until you
                            install it again. Your login, library and downloaded games stay on this device.</p>
                        <p><b>Everything:</b> also uninstalls its games, removes their Steam shortcuts,
                            signs you out and deletes its library and settings.</p>
                    </div>
                }
                strOKButtonText="Extension only"
                onOK={() => run("remove_extension", item)}
                strMiddleButtonText="Everything…"
                onMiddleButton={() => confirmRemoveEverything(item)}
            />
        );
    };

    const confirmRemoveEverything = async (item: ExtensionItem) => {
        const s = await call<[string], { name?: string; games?: number; error?: string }>(
            "extension_removal_summary", item.id);
        if (s.error) {
            setOutput(`ERROR: ${s.error}\n`);
            return;
        }
        const games = s.games ?? 0;
        const what = games === 0
            ? "It has no installed games."
            : `Its ${games} game(s) will be deleted from this device, files and Steam shortcuts.`;
        showModal(
            <ConfirmModal
                strTitle={`Remove ${item.name} and everything in it?`}
                strDescription={
                    <div>
                        <p>{what}</p>
                        <p>You'll be signed out, and its library and settings are deleted from this device.
                            This can't be undone.</p>
                    </div>
                }
                strOKButtonText="Remove everything"
                onOK={() => run("remove_extension", item, true)}
            />
        );
    };

    if (!info && !loadError) return <SteamSpinner />;

    const status = (item: ExtensionItem) => {
        if (!item.installed) return item.latest ? `Version ${item.latest}` : "";
        if (item.update) return `Installed ${item.installed} · update to ${item.latest}`;
        return `Installed ${item.installed}`;
    };

    return (
        <div style={{ padding: "0 15px", height: "100%", display: "flex" }}>
            <ScrollableWindowRelative>
                <PanelSection>
                    <div style={{ fontSize: "14px", color: "#8b929a", marginBottom: "8px" }}>
                        Built in: {info?.builtin.join(", ") || "none"}. Add the other stores you use below.
                    </div>
                    {(loadError || info?.error) && (
                        <div style={{ color: "#d94141", marginBottom: "8px" }}>
                            Couldn't load the extension list: {loadError || info?.error}
                        </div>
                    )}
                    <DialogButton disabled={!!busy} onClick={load} style={{ marginBottom: "8px" }}>
                        Check for updates
                    </DialogButton>
                </PanelSection>
                <PanelSection title="Extensions">
                    {info?.extensions.map(item => (
                        <Field
                            key={item.id}
                            label={item.name}
                            description={
                                <div>
                                    <div>{item.description}</div>
                                    <div style={{ color: item.update ? "#59bf40" : "#8b929a" }}>
                                        {status(item)}
                                        {!item.compatible && " · needs a newer GameVault"}
                                    </div>
                                </div>
                            }
                            childrenContainerWidth="max"
                        >
                            <Focusable style={{ display: "flex", gap: "8px" }}>
                                {(!item.installed || item.update) && item.latest && (
                                    <DialogButton
                                        style={{ minWidth: "110px" }}
                                        disabled={!!busy || !item.compatible}
                                        onClick={() => run("install_extension", item)}
                                    >
                                        {busy === item.id ? "Working…" : item.installed ? "Update" : "Install"}
                                    </DialogButton>
                                )}
                                {item.installed && (
                                    <DialogButton
                                        style={{ minWidth: "110px" }}
                                        disabled={!!busy}
                                        onClick={() => confirmRemove(item)}
                                    >
                                        Remove
                                    </DialogButton>
                                )}
                            </Focusable>
                        </Field>
                    ))}
                    {info && info.extensions.length === 0 && !info.error && (
                        <div style={{ color: "#8b929a" }}>No extensions available.</div>
                    )}
                </PanelSection>
                {(busy || output) && (
                    <PanelSection>
                        <textarea
                            ref={outputRef}
                            style={{ width: "100%", height: "180px" }}
                            value={output}
                            readOnly
                        />
                    </PanelSection>
                )}
            </ScrollableWindowRelative>
        </div>
    );
};
