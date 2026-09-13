import { sleep } from "@decky/ui";
import { toaster } from "@decky/api";
import { ContentType, ExecuteGetGameDetailsArgs, ExecuteInstallArgs, GameDetails, GameImages, LaunchOptions, ProgressUpdate } from "../Types/Types";
import { executeAction } from "./executeAction";
import Logger from "./logger";

export type QueueItemStatus = "queued" | "downloading" | "installing" | "done" | "error";

export interface QueueItem {
    shortname: string;
    title: string;
    initActionSet: string;
    status: QueueItemStatus;
    progress: number;
    description: string;
}

export interface QueueState {
    items: QueueItem[];
    isProcessing: boolean;
}

type QueueListener = (state: QueueState) => void;

const STORAGE_KEY = "gv_installQueue";
const logger = new Logger("InstallQueue");

class InstallQueue {
    private state: QueueState = {
        items: [],
        isProcessing: false,
    };
    private listeners: Set<QueueListener> = new Set();
    private cancelled = false;
    private runGeneration = 0;

    constructor() {
        this.restoreState();
    }

    subscribe(listener: QueueListener) {
        this.listeners.add(listener);
        listener(this.getState());
        return () => this.listeners.delete(listener);
    }

    private notify() {
        this.saveState();
        const snapshot = this.getState();
        this.listeners.forEach(l => l(snapshot));
    }

    private saveState() {
        try {
            // Only persist items that are still pending work
            const persistItems = this.state.items
                .filter(i => i.status === "queued" || i.status === "downloading" || i.status === "installing")
                .map(i => ({
                    shortname: i.shortname,
                    title: i.title,
                    initActionSet: i.initActionSet,
                    status: i.status,
                    progress: i.progress,
                    description: i.description,
                }));
            localStorage.setItem(STORAGE_KEY, JSON.stringify(persistItems));
        } catch (e) {
            logger.error("Failed to save queue state", e);
        }
    }

    private restoreState() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (!stored) return;
            const parsed = JSON.parse(stored);
            if (!Array.isArray(parsed) || parsed.length === 0) return;
            // Validate each item has required fields
            const items: QueueItem[] = parsed.filter((i: any) =>
                i && typeof i.shortname === "string" && typeof i.title === "string" &&
                typeof i.initActionSet === "string" && typeof i.status === "string"
            );
            if (items.length === 0) return;
            // Mark any "downloading" or "installing" items as "queued" since we lost
            // track of them — reconnect() will check their actual status
            this.state.items = items.map(i => ({
                ...i,
                progress: typeof i.progress === "number" ? i.progress : 0,
                description: typeof i.description === "string" ? i.description : "",
                status: i.status === "downloading" || i.status === "installing" ? "queued" : i.status,
                ...(i.status === "downloading" || i.status === "installing" ? { description: "Reconnecting..." } : {}),
            }));
        } catch (e) {
            logger.error("Failed to restore queue state", e);
        }
    }

    /**
     * Call on plugin mount to reconnect to any in-progress downloads
     * that survived a GameVault close/reopen.
     */
    async reconnect() {
        const pendingItems = this.state.items.filter(i => i.status === "queued");
        if (pendingItems.length === 0) return;

        // Check each item's progress to see if it's still downloading
        for (const item of pendingItems) {
            try {
                const progressResult = await executeAction<ExecuteGetGameDetailsArgs, ProgressUpdate>(
                    item.initActionSet, "GetProgress", { shortname: item.shortname }
                );
                if (progressResult && progressResult.Content) {
                    const progress = progressResult.Content;
                    if (progress.Percentage > 0 && progress.Percentage < 100) {
                        // Download still running in the background
                        item.status = "downloading";
                        item.progress = progress.Percentage;
                        item.description = progress.Description || "Downloading...";
                    } else if (progress.Percentage >= 100) {
                        // Download completed while we were away
                        item.status = "downloading";
                        item.progress = 100;
                        item.description = "Download complete, setting up...";
                    }
                }
            } catch (e) {
                logger.debug("Reconnect check failed for " + item.shortname, e);
            }
        }
        this.notify();
        // Start processing if we found active items
        if (this.state.items.some(i => i.status === "queued" || i.status === "downloading")) {
            this.start();
        }
    }

    add(shortname: string, title: string, initActionSet: string) {
        if (this.state.items.some(i => i.shortname === shortname && i.status !== "done" && i.status !== "error")) return;
        // Remove any completed/errored entry for this game first
        this.state.items = this.state.items.filter(i => i.shortname !== shortname || (i.status !== "done" && i.status !== "error"));
        this.state.items.push({
            shortname,
            title,
            initActionSet,
            status: "queued",
            progress: 0,
            description: "Queued",
        });
        this.notify();
        // Auto-start queue processing
        if (!this.state.isProcessing) {
            this.start();
        }
    }

    remove(shortname: string) {
        const item = this.state.items.find(i => i.shortname === shortname);
        if (item && item.status === "downloading") {
            // Cancel active download
            this.cancelItem(shortname);
            return;
        }
        this.state.items = this.state.items.filter(i => i.shortname !== shortname);
        this.notify();
    }

    async cancelItem(shortname: string) {
        const item = this.state.items.find(i => i.shortname === shortname);
        if (!item) return;
        if (item.status === "downloading") {
            try {
                await executeAction<ExecuteGetGameDetailsArgs, ContentType>(
                    item.initActionSet, "CancelInstall", { shortname }
                );
            } catch (e) {
                logger.error("Failed to cancel download", e);
            }
        }
        this.state.items = this.state.items.filter(i => i.shortname !== shortname);
        this.notify();
    }

    clear() {
        if (this.state.isProcessing) {
            this.cancelled = true;
        }
        // Cancel any active downloads
        const downloading = this.state.items.find(i => i.status === "downloading");
        if (downloading) {
            executeAction<ExecuteGetGameDetailsArgs, ContentType>(
                downloading.initActionSet, "CancelInstall", { shortname: downloading.shortname }
            ).catch(() => {});
        }
        this.state.items = [];
        this.state.isProcessing = false;
        this.notify();
    }

    clearCompleted() {
        this.state.items = this.state.items.filter(i => i.status !== "done" && i.status !== "error");
        this.notify();
    }

    moveUp(shortname: string) {
        const idx = this.state.items.findIndex(i => i.shortname === shortname);
        if (idx <= 0) return;
        const prev = this.state.items[idx - 1];
        // Can't move above an actively downloading/installing item
        if (prev.status === "downloading" || prev.status === "installing") return;
        [this.state.items[idx - 1], this.state.items[idx]] = [this.state.items[idx], this.state.items[idx - 1]];
        this.notify();
    }

    moveDown(shortname: string) {
        const idx = this.state.items.findIndex(i => i.shortname === shortname);
        if (idx < 0 || idx >= this.state.items.length - 1) return;
        [this.state.items[idx], this.state.items[idx + 1]] = [this.state.items[idx + 1], this.state.items[idx]];
        this.notify();
    }

    getState(): QueueState {
        return { ...this.state, items: this.state.items.map(i => ({ ...i })) };
    }

    getItemStatus(shortname: string): QueueItem | undefined {
        return this.state.items.find(i => i.shortname === shortname);
    }

    getQueuePosition(shortname: string): number {
        const queued = this.state.items.filter(i => i.status === "queued");
        const idx = queued.findIndex(i => i.shortname === shortname);
        return idx >= 0 ? idx + 1 : -1;
    }

    get activeCount(): number {
        return this.state.items.filter(i => i.status === "downloading" || i.status === "installing" || i.status === "queued").length;
    }

    get queuedCount(): number {
        return this.state.items.filter(i => i.status === "queued").length;
    }

    get isProcessing(): boolean {
        return this.state.isProcessing;
    }

    async start() {
        if (this.state.isProcessing) return;
        this.cancelled = false;
        this.runGeneration++;
        const myGeneration = this.runGeneration;
        this.state.isProcessing = true;
        this.notify();

        // Continuously drain the queue — new items added during processing
        // will be picked up automatically
        while (true) {
            if (this.cancelled || myGeneration !== this.runGeneration) break;
            const nextItem = this.state.items.find(i => i.status === "queued");
            if (!nextItem) break;
            await this.processItem(nextItem);
        }

        this.state.isProcessing = false;
        this.notify();

        // Toast completion summary
        const done = this.state.items.filter(i => i.status === "done").length;
        const errors = this.state.items.filter(i => i.status === "error").length;
        const total = done + errors;
        if (total > 0) {
            toaster.toast({
                title: "GameVault",
                body: errors > 0
                    ? `${done}/${total} games installed (${errors} failed)`
                    : `${done} game${done > 1 ? 's' : ''} installed successfully`,
            });
        }
    }

    private async processItem(item: QueueItem) {
        // Step 1: Start download
        item.status = "downloading";
        item.description = "Starting download...";
        this.notify();

        try {
            const downloadResult = await executeAction<ExecuteGetGameDetailsArgs, ContentType>(
                item.initActionSet, "Download", { shortname: item.shortname }
            );

            if (!downloadResult || downloadResult.Type !== "Progress") {
                item.status = "error";
                item.description = "Failed to start download";
                this.notify();
                return;
            }

            // Step 2: Poll progress (adaptive interval)
            let lastProgress = 0;
            let pollInterval = 1000;
            while (!this.cancelled) {
                await sleep(pollInterval);
                if (this.cancelled) break;
                // Check if this item was removed from queue while downloading
                if (!this.state.items.includes(item)) return;

                const progressResult = await executeAction<ExecuteGetGameDetailsArgs, ProgressUpdate>(
                    item.initActionSet, "GetProgress", { shortname: item.shortname }
                );

                if (!progressResult) continue;

                const progress = progressResult.Content;
                if (progress.Error) {
                    item.status = "error";
                    item.description = progress.Error;
                    this.notify();
                    return;
                }

                item.progress = progress.Percentage;
                item.description = progress.Description;
                this.notify();

                if (progress.Percentage >= 100) break;

                // Adaptive polling: slow down if progress isn't moving
                if (progress.Percentage === lastProgress) {
                    pollInterval = Math.min(pollInterval + 500, 5000);
                } else {
                    pollInterval = 1000;
                }
                lastProgress = progress.Percentage;
            }

            if (this.cancelled) {
                await executeAction<ExecuteGetGameDetailsArgs, ContentType>(
                    item.initActionSet, "CancelInstall", { shortname: item.shortname }
                );
                item.status = "queued";
                item.description = "Cancelled";
                this.notify();
                return;
            }

            // Step 3: Create Steam shortcut and install
            item.status = "installing";
            item.description = "Setting up Steam shortcut...";
            this.notify();

            // Get game details for the name
            const detailsResult = await executeAction<ExecuteGetGameDetailsArgs, GameDetails>(
                item.initActionSet, "GetDetails", { shortname: item.shortname }
            );

            if (!detailsResult) {
                item.status = "error";
                item.description = "Failed to get game details";
                this.notify();
                return;
            }

            const gameName = detailsResult.Content.Name;
            const existingId = detailsResult.Content.SteamClientID;

            // Get or create Steam shortcut
            let steamId: number;
            if (existingId && existingId !== "") {
                steamId = parseInt(existingId, 10);
                // @ts-ignore
                const apps = appStore.allApps.filter(app => app.appid === steamId);
                if (apps.length === 0) {
                    steamId = await SteamClient.Apps.AddShortcut("Name", "/bin/bash", "", "");
                }
            } else {
                steamId = await SteamClient.Apps.AddShortcut("Name", "/bin/bash", "", "");
            }
            if (!steamId || steamId <= 0) {
                item.status = "error";
                item.description = "Failed to create Steam shortcut";
                this.notify();
                return;
            }

            // @ts-ignore
            await appDetailsCache.FetchDataForApp(steamId);
            await appDetailsStore.RequestAppDetails(steamId);
            SteamClient.Apps.SetShortcutName(steamId, gameName);

            // Call Install action to get launch options
            const installResult = await executeAction<ExecuteInstallArgs, ContentType>(
                item.initActionSet, "Install",
                { shortname: item.shortname, steamClientID: steamId.toString() }
            );

            if (installResult && installResult.Type === "LaunchOptions") {
                const launchOptions = installResult.Content as LaunchOptions;
                // @ts-ignore
                await appDetailsCache.FetchDataForApp(steamId);
                await appDetailsStore.RequestAppDetails(steamId);
                SteamClient.Apps.SetAppLaunchOptions(steamId, launchOptions.Options);
                SteamClient.Apps.SetShortcutName(steamId, gameName);
                SteamClient.Apps.SetShortcutExe(steamId, launchOptions.Exe);
                SteamClient.Apps.SetShortcutStartDir(steamId, launchOptions.WorkingDir);

                if (launchOptions.Compatibility) {
                    // @ts-ignore
                    const defaultProton = settingsStore.settings.strCompatTool;
                    if (defaultProton) {
                        SteamClient.Apps.SpecifyCompatTool(steamId, defaultProton);
                    } else {
                        try {
                            // @ts-ignore
                            const compatTools = await SteamClient.Apps.GetAvailableCompatTools(1);
                            const firstAvailable = compatTools.filter((tool: any) =>
                                tool.strToolName.startsWith('proton') &&
                                tool.strToolName.indexOf('experimental') === -1
                            );
                            if (firstAvailable.length > 0) {
                                SteamClient.Apps.SpecifyCompatTool(steamId, firstAvailable[0].CompatToolName);
                            }
                        } catch (e) {
                            logger.error("Error getting compat tools", e);
                        }
                    }
                } else {
                    SteamClient.Apps.SpecifyCompatTool(steamId, "");
                }
            }

            // Step 4: Set images
            item.description = "Setting up artwork...";
            this.notify();

            const imageResult = await executeAction<ExecuteGetGameDetailsArgs, GameImages>(
                item.initActionSet, "GetJsonImages", { shortname: item.shortname }
            );

            if (imageResult) {
                const images = imageResult.Content;
                if (images.Grid) await SteamClient.Apps.SetCustomArtworkForApp(steamId, images.Grid, 'png', 0);
                if (images.Hero) await SteamClient.Apps.SetCustomArtworkForApp(steamId, images.Hero, 'png', 1);
                if (images.Logo) await SteamClient.Apps.SetCustomArtworkForApp(steamId, images.Logo, 'png', 2);
                if (images.GridH) await SteamClient.Apps.SetCustomArtworkForApp(steamId, images.GridH, 'png', 3);
            }

            item.status = "done";
            item.progress = 100;
            item.description = "Installed";
            this.notify();

        } catch (e) {
            logger.error("Error processing queue item", e);
            item.status = "error";
            item.description = `Error: ${e}`;
            this.notify();
        }
    }
}

// Singleton instance
export const installQueue = new InstallQueue();
