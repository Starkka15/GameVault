import { DialogButton, Focusable, PanelSection, SteamSpinner } from "@decky/ui";
import { call } from "@decky/api";
import { FC, useEffect, useState } from "react";
import { ScrollableWindowRelative } from './ScrollableWindow';
import Logger from "./Utils/logger";

interface DiskSpace {
    location: string;
    path: string;
    free: string;
    free_bytes: number;
    total: string;
    total_bytes: number;
    used_percent: number;
}

interface StoreInfo {
    name: string;
    size: string;
    size_bytes: number;
    count: number;
}

interface GameInfo {
    shortname: string;
    store: string;
    title: string;
    size: string;
    size_bytes: number;
}

interface StorageStats {
    total_used: string;
    total_used_bytes: number;
    total_games: number;
    stores: StoreInfo[];
    games: GameInfo[];
    disk_spaces: DiskSpace[];
}

const STORE_COLORS: Record<string, string> = {
    "GOG": "#a855f7",
    "Epic": "#3b82f6",
    "Amazon": "#f59e0b",
    "itch.io": "#ef4444",
};

const StorageBar: FC<{ label: string; value: number; max: number; color: string; detail: string }> = ({ label, value, max, color, detail }) => {
    const percent = max > 0 ? Math.min((value / max) * 100, 100) : 0;
    return (
        <div style={{ marginBottom: "8px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px", fontSize: "13px" }}>
                <span>{label}</span>
                <span style={{ color: "#b0b0b0" }}>{detail}</span>
            </div>
            <div style={{ width: "100%", height: "12px", backgroundColor: "#2a2a3a", borderRadius: "6px", overflow: "hidden" }}>
                <div style={{
                    width: `${percent}%`,
                    height: "100%",
                    backgroundColor: color,
                    borderRadius: "6px",
                    transition: "width 0.3s ease",
                }} />
            </div>
        </div>
    );
};

export const StorageTab: FC = () => {
    const [stats, setStats] = useState<StorageStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const logger = new Logger("StorageTab");

    const fetchStats = async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await call<[], { Type: string; Content: StorageStats }>("get_storage_stats");
            if (res && res.Type === "StorageStats") {
                setStats(res.Content);
            } else {
                setError("Failed to load storage stats");
            }
        } catch (e) {
            logger.error("Error fetching storage stats:", e);
            setError("Failed to load storage stats");
        }
        setLoading(false);
    };

    useEffect(() => {
        fetchStats();
    }, []);

    if (loading) {
        return <SteamSpinner />;
    }

    if (error || !stats) {
        return (
            <PanelSection>
                <div style={{ textAlign: "center", padding: "20px" }}>
                    <p>{error || "No data available"}</p>
                    <DialogButton onClick={fetchStats}>Retry</DialogButton>
                </div>
            </PanelSection>
        );
    }

    const maxStoreBytes = stats.stores.length > 0 ? Math.max(...stats.stores.map(s => s.size_bytes)) : 1;

    return (
        <div style={{ padding: '0 15px', height: '100%', display: 'flex' }}>
            <ScrollableWindowRelative>
                {/* Summary */}
                <div style={{
                    display: "flex",
                    justifyContent: "space-around",
                    padding: "12px 0",
                    marginBottom: "12px",
                    borderBottom: "1px solid #3a3a4a",
                }}>
                    <div style={{ textAlign: "center" }}>
                        <div style={{ fontSize: "22px", fontWeight: "bold" }}>{stats.total_used}</div>
                        <div style={{ fontSize: "12px", color: "#b0b0b0" }}>Total Used</div>
                    </div>
                    <div style={{ textAlign: "center" }}>
                        <div style={{ fontSize: "22px", fontWeight: "bold" }}>{stats.total_games}</div>
                        <div style={{ fontSize: "12px", color: "#b0b0b0" }}>Games Installed</div>
                    </div>
                </div>

                {/* Disk Space */}
                {stats.disk_spaces.length > 0 && (
                    <div style={{ marginBottom: "16px" }}>
                        <h3 style={{ marginBottom: "8px" }}>Disk Space</h3>
                        {stats.disk_spaces.map((disk, i) => (
                            <StorageBar
                                key={i}
                                label={disk.location}
                                value={disk.total_bytes - disk.free_bytes}
                                max={disk.total_bytes}
                                color={disk.used_percent > 90 ? "#ef4444" : disk.used_percent > 75 ? "#f59e0b" : "#22c55e"}
                                detail={`${disk.free} free / ${disk.total}`}
                            />
                        ))}
                    </div>
                )}

                {/* Per-store breakdown */}
                {stats.stores.length > 0 && (
                    <div style={{ marginBottom: "16px" }}>
                        <h3 style={{ marginBottom: "8px" }}>Storage by Store</h3>
                        {stats.stores.map((store, i) => (
                            <StorageBar
                                key={i}
                                label={store.name}
                                value={store.size_bytes}
                                max={maxStoreBytes}
                                color={STORE_COLORS[store.name] || "#6b7280"}
                                detail={`${store.size} (${store.count} game${store.count !== 1 ? 's' : ''})`}
                            />
                        ))}
                    </div>
                )}

                {/* Game list */}
                {stats.games.length > 0 && (
                    <div style={{ marginBottom: "16px" }}>
                        <h3 style={{ marginBottom: "8px" }}>Installed Games</h3>
                        <Focusable style={{ display: "flex", flexDirection: "column" }}>
                            {stats.games.map((game, i) => (
                                <div key={i} style={{
                                    display: "flex",
                                    justifyContent: "space-between",
                                    alignItems: "center",
                                    padding: "8px 4px",
                                    borderBottom: "1px solid #2a2a3a",
                                }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{
                                            fontSize: "14px",
                                            whiteSpace: "nowrap",
                                            overflow: "hidden",
                                            textOverflow: "ellipsis",
                                        }}>{game.title}</div>
                                        <div style={{ fontSize: "11px", color: "#b0b0b0" }}>
                                            <span style={{ color: STORE_COLORS[game.store] || "#6b7280" }}>{game.store}</span>
                                            {" - "}{game.size}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </Focusable>
                    </div>
                )}

                {stats.games.length === 0 && stats.stores.length === 0 && (
                    <div style={{ textAlign: "center", padding: "40px 0", color: "#b0b0b0" }}>
                        <p>No games installed yet.</p>
                        <p style={{ fontSize: "13px" }}>Install games from the store tabs to see storage usage here.</p>
                    </div>
                )}

                {/* Refresh button */}
                <div style={{ padding: "8px 0 16px" }}>
                    <DialogButton onClick={fetchStats} disabled={loading}>
                        {loading ? "Loading..." : "Refresh"}
                    </DialogButton>
                </div>
            </ScrollableWindowRelative>
        </div>
    );
};
