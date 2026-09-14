import { AppDetails } from "@decky/ui";

type AppDetailsStore = {
    GetAppDetails: (appId: number) => AppDetails | undefined;
    RequestAppDetails(appId: number): Promise<void>;
};