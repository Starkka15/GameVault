import { WindowRouter, WindowStore } from "@decky/ui";

type SteamUiStore = {
    MainRunningAppID?: number;
    WindowStore: WindowStoreEx;
};

interface WindowStoreEx extends WindowStore {
    GamepadUIMainWindowInstance?: WindowInstance;
}
interface WindowInstance extends WindowRouter {
    LocationPathName: string;
}