import { LaunchOptions } from "../Types/Types";
import Logger from "./logger";

export enum AppRunStateChange {
    START,
    END,
    BOTH
}

export function gameIDFromAppID(appid: number) {
    let game = appStore.GetAppOverviewByAppID(appid);

    if (game) {
        return game.m_gameid;
    } else {
        return -1;
    }
};

export async function getAppDetails(appId: number | string) {
    const id = typeof appId === 'string' ? parseInt(appId) : appId
    await appDetailsStore.RequestAppDetails(id);
    return appDetailsStore.GetAppDetails(id);
}

export function runApp(appId: number, onAppClose?: () => void, onAppLaunch?: () => void) {
    const logger = new Logger('runApp');
    logger.debug(`Running appId: ${appId}`)
    if (onAppLaunch) {
        const { unregister } = registerForAppRunStateChange(appId, () => {
            onAppLaunch();
            unregister();
        }, AppRunStateChange.START);
        // Auto-unregister after 60s if app never starts
        setTimeout(() => { try { unregister(); } catch (_) {} }, 60000);
    }
    if (onAppClose) {
        const { unregister } = registerForAppRunStateChange(appId, () => {
            // Add a delay due to UI not updating in time - this is a workaround for now
            setTimeout(() => {
                logger.debug(`App ${appId} closed running onAppClose callback`);
                onAppClose();
            }
                , 1000);
            unregister();
        }, AppRunStateChange.END);
        // Auto-unregister after 24h if app never closes (safety net)
        setTimeout(() => { try { unregister(); } catch (_) {} }, 86400000);
    }
    let gid = gameIDFromAppID(appId);
    if (gid && gid !== -1) SteamClient.Apps.RunGame(gid as string, "", -1, 100);
}

export function registerForAppRunStateChange(appId: number, callback: () => void, stateChange: AppRunStateChange): { unregister: () => void; } {
    return SteamClient.GameSessions.RegisterForAppLifetimeNotifications((data: { unAppID: number; nInstanceID: number; bRunning: boolean; }) => {
        if (data.unAppID !== appId) return;
        switch (stateChange) {
            case AppRunStateChange.START:
                if (data.bRunning) callback();
                break;
            case AppRunStateChange.END:
                if (!data.bRunning) callback();
                break;
            case AppRunStateChange.BOTH:
                callback();
        }
    });
}

/**
 * Apply the extension's compatibility choice to a shortcut.
 *
 * Compatibility=true: give the shortcut Steam's default Proton (or the first
 * non-experimental Proton when no default is set).
 *
 * Compatibility=false (a native launcher that does its own Proton work, like
 * EA/Maxima or Optima): leave Steam's compat setting alone. A shortcut that
 * was never given a tool runs native on every Steam client. Calling
 * SpecifyCompatTool(id, "") used to mean "no tool", but the 64-bit Steam
 * client (steamrt64, Nov 2026) reads "" as "Default", which is Proton, and
 * wraps the launcher in Proton + Steam Linux Runtime. So "" is only sent
 * when the shortcut currently reports a tool, which is what clears it on
 * older clients; on the new client nothing else can clear it anyway.
 */
export async function applyCompatTool(id: number, compatibility: boolean | undefined) {
    const logger = new Logger("applyCompatTool");
    const apps = SteamClient.Apps as any;

    if (compatibility) {
        // @ts-ignore
        const defaultProton: string | undefined = settingsStore.settings.strCompatTool;
        if (defaultProton) {
            logger.debug("Setting compat tool", id, defaultProton);
            apps.SpecifyCompatTool(id, defaultProton);
            return;
        }
        // GetAvailableCompatTools no longer exists on the 64-bit client.
        if (typeof apps.GetAvailableCompatTools !== "function") {
            logger.debug("No default compat tool and no tool list; using proton-stable", id);
            apps.SpecifyCompatTool(id, "proton-stable");
            return;
        }
        try {
            const compatTools = await apps.GetAvailableCompatTools(id);
            const firstAvailable = compatTools.filter((tool: any) =>
                tool.strToolName.startsWith('proton') &&
                tool.strToolName.indexOf('experimental') === -1
            );
            if (firstAvailable.length > 0) {
                apps.SpecifyCompatTool(id, firstAvailable[0].strToolName);
            }
        } catch (e) {
            logger.error("Error getting compat tools", e);
        }
        return;
    }

    let current: string | undefined;
    try {
        current = (await getAppDetails(id))?.strCompatToolName;
    } catch (e) {
        logger.error("Could not read app details", id, e);
    }
    if (current) {
        logger.debug("Clearing compat tool", id, current);
        apps.SpecifyCompatTool(id, "");
    } else {
        logger.debug("No compat tool set; leaving native", id);
    }
}

export function configureShortcut(id: number, launchOptions: LaunchOptions) {
    const logger = new Logger("configureShortcut");

    if (launchOptions) {
        logger.debug("launchOptions: ", launchOptions);
        SteamClient.Apps.SetAppLaunchOptions(id, launchOptions.Options);
        SteamClient.Apps.SetShortcutExe(id, launchOptions.Exe);
        SteamClient.Apps.SetShortcutStartDir(id, launchOptions.WorkingDir);

        if (launchOptions.Compatibility) {
            SteamClient.Apps.SpecifyCompatTool(id, launchOptions.CompatToolName ?? '');
        }
    }
}