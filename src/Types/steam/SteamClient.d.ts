interface SystemSuspendInfo {
    state: number;
}

interface SystemResumeInfo {
    state: number;
    bGameSuspended: boolean;
}

type AppResolutionOverrideConstants = "Default" | "Native";

interface SteamClient {
    Apps: {
        AddShortcut: (appName: string, executablePath: string, directory: string, launchOptions: string) => Promise<number>;
        GetResolutionOverrideForApp: (appId: number) => Promise<AppResolutionOverrideConstants | string>;
        RegisterForAppDetails: (appId: number, callback: (details: AppDetails) => void) => { unregister: () => void; };
        RemoveShortcut: (appId: number) => void;
        RunGame: (gameId: string, _1: string, _2: number, _3: number) => void;
        TerminateApp: (gameId: string, _1: boolean) => void;
        SetAppHidden: (appId: number, value: boolean) => void;
        SetAppLaunchOptions: (appId: number, options: string) => void;
        SetAppResolutionOverride: (appId: number, resolution: AppResolutionOverrideConstants | string) => void;
        SetShortcutName: (appId: number, name: string) => void;
        SetShortcutLaunchOptions: (appId: number, options: string) => void;
        SetShortcutExe: (appId: number, exe: string) => void;
        SetShortcutStartDir: (appId: number, directory: string) => void;
        SetCustomArtworkForApp: (appId: number, base64Image: string, imageType: string, assetType: AppArtworkAssetType) => Promise<any>;
        SpecifyCompatTool: (appId: number, strToolName: string) => void;
        GetAvailableCompatTools: (appId: number) => Promise<CompatTool[]>;
    };
    Input: {
        RegisterForControllerInputMessages: (callback: (e: ControllerInputMessage[]) => void) => { unregister: () => void; };
    };
    GameSessions: {
        RegisterForAppLifetimeNotifications: (callback: (data: LifetimeNotification) => void) => { unregister: () => void; };
    };
    User: {
        RegisterForLoginStateChange: (callback: (username: string) => void) => { unregister: () => void; };
        RegisterForPrepareForSystemSuspendProgress: (callback: (info: SystemSuspendInfo) => void) => { unregister: () => void; };
        RegisterForResumeSuspendedGamesProgress: (callback: (info: SystemResumeInfo) => void) => { unregister: () => void; };
        StartRestart: () => void;
    };
    System: {
        DisplayManager: {
            RegisterForStateChanges: (callback: () => void) => { unregister: () => void; };
        };
    };
    Installs: {
        OpenInstallWizard: (appIds: number[]) => void;
    }
}

interface CompatTool {
    strToolName: string;
    CompatToolName: string;
    strDisplayName?: string;
}

interface ControllerInputMessage {
    nA: number;
    bS: boolean;
}

// Steam UI internal stores/caches — untyped internals exposed on the global scope.
declare const appDetailsCache: any;
declare const settingsStore: any;