import { Navigation } from "@decky/ui";
import { FC, useEffect, useState } from "react";
import { QueueState, installQueue } from "../Utils/installQueue";
import { FaDownload } from "react-icons/fa";

export const DownloadBadge: FC = () => {
    const [queueState, setQueueState] = useState<QueueState>(installQueue.getState());

    useEffect(() => {
        const unsub = installQueue.subscribe(setQueueState);
        return () => { unsub(); };
    }, []);

    const activeItems = queueState.items.filter(
        i => i.status === "downloading" || i.status === "installing" || i.status === "queued"
    );

    if (activeItems.length === 0) return null;

    const currentDownload = queueState.items.find(i => i.status === "downloading");

    return (
        <div
            onClick={() => Navigation.Navigate('/gamevault-downloads')}
            style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '8px 12px',
                backgroundColor: '#1a1a2e',
                borderRadius: '8px',
                border: '1px solid #2a2a4a',
                cursor: 'pointer',
                marginTop: '8px',
            }}
        >
            <FaDownload style={{
                color: '#1a9fff',
                fontSize: '14px',
                animation: currentDownload ? 'gv-badge-pulse 1.5s ease-in-out infinite' : 'none',
            }} />
            <div style={{ flex: 1, minWidth: 0 }}>
                {currentDownload ? (
                    <div style={{
                        fontSize: '12px',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                    }}>
                        {currentDownload.title} Ã¢â‚¬â€ {Math.round(currentDownload.progress)}%
                    </div>
                ) : (
                    <div style={{ fontSize: '12px' }}>
                        {activeItems.length} queued
                    </div>
                )}
            </div>
            {activeItems.length > 1 && (
                <div style={{
                    backgroundColor: '#1a9fff',
                    borderRadius: '10px',
                    padding: '1px 6px',
                    fontSize: '11px',
                    fontWeight: 'bold',
                    color: '#fff',
                }}>
                    +{activeItems.length - (currentDownload ? 1 : 0)}
                </div>
            )}
            <style>{`
                @keyframes gv-badge-pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.5; }
                }
            `}</style>
        </div>
    );
};
