import { call, toaster } from "@decky/api";
import { LaunchOptions } from "../Types/Types";
import Logger from "./logger";

export interface ExtensionItem {
    id: string;
    name: string;
    description: string;
    latest: string | null;
    installed: string | null;
    update: boolean;
    compatible: boolean;
}

export interface ExtensionsInfo {
    builtin: string[];
    extensions: ExtensionItem[];
    error: string;
}

const logger = new Logger("extensions");

export async function getExtensions(): Promise<ExtensionsInfo> {
    const res = await call<[], { Type: string; Content: ExtensionsInfo }>("get_extensions");
    return res.Content;
}

/**
 * Point the Steam shortcuts of an extension's installed games at wherever the
 * extension's launcher now lives. Installing or updating an extension can move it
 * (stores that used to ship inside GameVault did), and a shortcut still aimed at
 * the old path would not start. The compatibility tool is left as it is.
 */
export async function relinkExtension(id: string): Promise<number> {
    const items = await call<[string], { appId: number; launchOptions: LaunchOptions }[]>(
        "relink_extension", id);
    let done = 0;
    for (const { appId, launchOptions } of items ?? []) {
        try {
            if (!launchOptions?.Exe) continue;
            SteamClient.Apps.SetShortcutExe(appId, launchOptions.Exe);
            SteamClient.Apps.SetShortcutStartDir(appId, launchOptions.WorkingDir);
            SteamClient.Apps.SetAppLaunchOptions(appId, launchOptions.Options);
            done++;
        } catch (e) {
            logger.error(`relink ${id} app ${appId}: ${e}`);
        }
    }
    logger.log(`relinked ${done} shortcut(s) for ${id}`);
    return done;
}

/**
 * At plugin start: finish the one-time move of formerly built-in stores (the
 * backend installs them in the background; their shortcuts are fixed here), then
 * say once if any installed extension has an update.
 */
export function startExtensionChecks() {
    let stopped = false;
    const deadline = Date.now() + 10 * 60 * 1000;

    const pollMigration = async () => {
        if (stopped) return;
        try {
            const res = await call<[], { running: boolean; ids: string[] }>("take_pending_relinks");
            for (const id of res.ids) {
                const n = await relinkExtension(id);
                toaster.toast({
                    title: "GameVault",
                    body: `${id} is now an extension; ${n} game shortcut(s) updated.`,
                });
            }
            if (res.running && Date.now() < deadline) {
                setTimeout(pollMigration, 5000);
            }
        } catch (e) {
            logger.error(`migration poll: ${e}`);
        }
    };

    const checkUpdates = async () => {
        if (stopped) return;
        try {
            const info = await getExtensions();
            const updates = info.extensions.filter(e => e.update && e.compatible);
            if (updates.length) {
                toaster.toast({
                    title: "GameVault extension updates",
                    body: updates.map(e => `${e.name} ${e.latest}`).join(", ")
                        + " — About › Extensions",
                });
            }
        } catch (e) {
            logger.error(`update check: ${e}`);
        }
    };

    setTimeout(pollMigration, 3000);
    setTimeout(checkUpdates, 30000);
    return () => { stopped = true; };
}
