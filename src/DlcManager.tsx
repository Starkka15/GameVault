import { FC, useEffect, useState } from "react";
import { ModalRoot, DialogButton, PanelSection, PanelSectionRow, SteamSpinner, ProgressBarWithInfo, ConfirmModal, showModal, Focusable } from "@decky/ui";
import { executeAction } from "./Utils/executeAction";
import { ContentType, ExecuteArgs, ProgressUpdate, SuccessContent } from "./Types/Types";
import Logger from "./Utils/logger";

// One DLC row as reported by gog.py get_dlcs.
interface DlcInfo {
    Id: string;
    Title: string;
    Size: string;
    Installed: boolean;
}
interface DlcListContent extends ContentType {
    Dlcs: DlcInfo[];
    Error?: string;
}
interface DlcListArgs extends ExecuteArgs {
    shortName: string;
}
interface DlcActionArgs extends ExecuteArgs {
    shortName: string;
    dlcId: string;
}

export interface DlcManagerProperties {
    
    initActionSet: string;   // "GOGActions"
    shortName: string;
    name: string;
    closeModal?: () => void;
    refreshParent?: () => void;
}

export const DlcManager: FC<DlcManagerProperties> = ({
    initActionSet, shortName, name, closeModal, refreshParent,
}) => {
    const logger = new Logger("DlcManager");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [dlcs, setDlcs] = useState<DlcInfo[]>([]);
    // dlcId currently downloading -> its progress (null = not downloading)
    const [busyId, setBusyId] = useState<string | null>(null);
    const [progress, setProgress] = useState<ProgressUpdate | null>(null);

    const loadDlcs = async () => {
        setLoading(true);
        setError("");
        const res = await executeAction<DlcListArgs, DlcListContent>(initActionSet, "GetDlcs", { shortName });
        setLoading(false);
        if (!res || !res.Content) {
            setError("Could not load DLC list.");
            return;
        }
        if (res.Content.Error) {
            setError(res.Content.Error);
        }
        setDlcs(res.Content.Dlcs || []);
    };

    useEffect(() => { loadDlcs(); }, []);

    // Poll GetProgress until the DLC download finishes, then refresh the list.
    const pollProgress = () => {
        const timer = setInterval(async () => {
            const res = await executeAction<DlcListArgs, ProgressUpdate>(initActionSet, "GetProgress", { shortName });
            const p = res?.Content as ProgressUpdate | undefined;
            if (!p) return;
            setProgress(p);
            if (p.Error) {
                clearInterval(timer);
                setError(p.Error);
                setBusyId(null);
                setProgress(null);
                return;
            }
            if (p.Percentage >= 100) {
                clearInterval(timer);
                setBusyId(null);
                setProgress(null);
                refreshParent && refreshParent();
                await loadDlcs();
            }
        }, 1000);
    };

    const installDlc = async (dlc: DlcInfo) => {
        logger.log(`install DLC ${dlc.Id} (${dlc.Title})`);
        setBusyId(dlc.Id);
        setProgress({ Percentage: 0, Description: "StartingÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦" } as ProgressUpdate);
        await executeAction<DlcActionArgs, ContentType>(initActionSet, "InstallDlc", { shortName, dlcId: dlc.Id });
        pollProgress();
    };

    const removeDlc = async (dlc: DlcInfo) => {
        logger.log(`remove DLC ${dlc.Id} (${dlc.Title})`);
        setBusyId(dlc.Id);
        const res = await executeAction<DlcActionArgs, SuccessContent>(initActionSet, "RemoveDlc", { shortName, dlcId: dlc.Id });
        setBusyId(null);
        if (res?.Type === "Error") {
            setError("Failed to remove DLC.");
        }
        refreshParent && refreshParent();
        await loadDlcs();
    };

    const confirmRemove = (dlc: DlcInfo) => {
        showModal(
            <ConfirmModal
                strTitle={"Remove DLC"}
                strDescription={`Remove "${dlc.Title}"? Its files will be deleted; the base game stays installed.`}
                onOK={() => { removeDlc(dlc); }}
            />
        );
    };

    return (
        <ModalRoot bAllowFullSize={true} closeModal={closeModal}>
            <div style={{ fontWeight: "bold", fontSize: "1.3em", marginBottom: "4px" }}>
                DLC ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â {name}
            </div>
            <div style={{ fontSize: "0.8em", opacity: 0.6, marginBottom: "8px" }}>
                Note: DLC that replaces existing game files (e.g. uncensor / patch DLC) can't be
                fully removed ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â Remove clears its marker and any files it added, but modified base
                files stay as-is. Reinstalling re-applies it.
            </div>

            {loading && <SteamSpinner />}

            {!loading && error && (
                <div style={{ color: "#e35", marginBottom: "8px" }}>{error}</div>
            )}

            {!loading && !error && dlcs.length === 0 && (
                <div style={{ opacity: 0.7 }}>This game has no DLC.</div>
            )}

            {!loading && dlcs.length > 0 && (
                <PanelSection>
                    {dlcs.map((dlc) => {
                        const downloading = busyId === dlc.Id && progress != null;
                        return (
                            <PanelSectionRow key={dlc.Id}>
                                <Focusable style={{ display: "flex", alignItems: "center", gap: "10px", width: "100%" }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontWeight: "bold" }}>{dlc.Title}</div>
                                        <div style={{ fontSize: "0.8em", opacity: 0.7 }}>
                                            {dlc.Installed ? "Installed" : "Not installed"}
                                            {dlc.Size ? ` ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· ${dlc.Size}` : ""}
                                        </div>
                                        {downloading && (
                                            <ProgressBarWithInfo
                                                nProgress={progress!.Percentage}
                                                indeterminate={progress!.Percentage <= 0}
                                                sOperationText={progress!.Description || "InstallingÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦"}
                                            />
                                        )}
                                    </div>
                                    <div style={{ flex: "0 0 auto" }}>
                                        {dlc.Installed ? (
                                            <DialogButton
                                                disabled={busyId != null}
                                                onClick={() => confirmRemove(dlc)}
                                                style={{ minWidth: "110px" }}
                                            >
                                                Remove
                                            </DialogButton>
                                        ) : (
                                            <DialogButton
                                                disabled={busyId != null}
                                                onClick={() => installDlc(dlc)}
                                                style={{ minWidth: "110px" }}
                                            >
                                                {busyId === dlc.Id ? "InstallingÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦" : "Install"}
                                            </DialogButton>
                                        )}
                                    </div>
                                </Focusable>
                            </PanelSectionRow>
                        );
                    })}
                </PanelSection>
            )}
        </ModalRoot>
    );
};
