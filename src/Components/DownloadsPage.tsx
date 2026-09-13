import { DialogBody, DialogButton, Focusable, ProgressBar } from "@decky/ui";
import { FC, useEffect, useState } from "react";
import { QueueItem, QueueState, installQueue } from "../Utils/installQueue";
import { FaArrowDown, FaArrowUp, FaTimes, FaTrash } from "react-icons/fa";

export const DownloadsPage: FC = () => {
    const [queueState, setQueueState] = useState<QueueState>(installQueue.getState());

    useEffect(() => {
        const unsub = installQueue.subscribe(setQueueState);
        return () => { unsub(); };
    }, []);

    const downloading = queueState.items.filter(i => i.status === "downloading" || i.status === "installing");
    const queued = queueState.items.filter(i => i.status === "queued");
    const completed = queueState.items.filter(i => i.status === "done");
    const errored = queueState.items.filter(i => i.status === "error");

    const isEmpty = queueState.items.length === 0;

    return (
        <DialogBody>
            <style>{`
                @keyframes gv-pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.6; }
                }
            `}</style>
            <Focusable style={{ padding: '15px' }}>
                <div style={{ fontSize: '24px', fontWeight: 'bold', marginBottom: '20px' }}>
                    Downloads
                </div>

                {isEmpty && (
                    <div style={{
                        textAlign: 'center',
                        padding: '60px 20px',
                        color: '#8b929a',
                        fontSize: '16px'
                    }}>
                        No downloads in progress.
                        <br />
                        <span style={{ fontSize: '13px' }}>
                            Install a game from the store to see it here.
                        </span>
                    </div>
                )}

                {/* In Progress */}
                {downloading.length > 0 && (
                    <div style={{ marginBottom: '24px' }}>
                        <SectionHeader title="In Progress" count={downloading.length} />
                        {downloading.map(item => (
                            <DownloadingItem key={item.shortname} item={item} />
                        ))}
                    </div>
                )}

                {/* Queued */}
                {queued.length > 0 && (
                    <div style={{ marginBottom: '24px' }}>
                        <SectionHeader title="Queued" count={queued.length} />
                        {queued.map((item, idx) => (
                            <QueuedItem
                                key={item.shortname}
                                item={item}
                                isFirst={idx === 0 && downloading.length === 0}
                                isLast={idx === queued.length - 1}
                            />
                        ))}
                    </div>
                )}

                {/* Completed */}
                {completed.length > 0 && (
                    <div style={{ marginBottom: '24px' }}>
                        <SectionHeader title="Completed" count={completed.length} />
                        {completed.map(item => (
                            <CompletedItem key={item.shortname} item={item} />
                        ))}
                        <DialogButton
                            onClick={() => installQueue.clearCompleted()}
                            style={{
                                marginTop: '8px',
                                fontSize: '12px',
                                padding: '6px 16px',
                                minWidth: 'initial',
                                width: 'auto',
                            }}
                        >
                            Clear Completed
                        </DialogButton>
                    </div>
                )}

                {/* Errors */}
                {errored.length > 0 && (
                    <div style={{ marginBottom: '24px' }}>
                        <SectionHeader title="Failed" count={errored.length} />
                        {errored.map(item => (
                            <ErrorItem key={item.shortname} item={item} />
                        ))}
                    </div>
                )}
            </Focusable>
        </DialogBody>
    );
};

const SectionHeader: FC<{ title: string; count: number }> = ({ title, count }) => (
    <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        marginBottom: '12px',
    }}>
        <div style={{
            fontSize: '14px',
            fontWeight: 'bold',
            textTransform: 'uppercase',
            color: '#b8bcbf',
            letterSpacing: '1px',
        }}>
            {title}
        </div>
        <div style={{
            backgroundColor: '#3d4450',
            borderRadius: '10px',
            padding: '1px 8px',
            fontSize: '12px',
            color: '#b8bcbf',
        }}>
            {count}
        </div>
        <div style={{ flex: 1, height: '1px', backgroundColor: '#3d4450' }} />
    </div>
);

const DownloadingItem: FC<{ item: QueueItem }> = ({ item }) => (
    <Focusable style={{
        display: 'flex',
        alignItems: 'center',
        gap: '16px',
        padding: '12px 16px',
        backgroundColor: '#1a1a2e',
        borderRadius: '8px',
        border: '1px solid #2a2a4a',
        marginBottom: '8px',
    }}>
        <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
                fontSize: '15px',
                fontWeight: 'bold',
                marginBottom: '6px',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
            }}>
                {item.title}
            </div>
            <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                marginBottom: '4px',
                fontSize: '11px',
                color: '#969696',
            }}>
                <span>{item.description}</span>
                <span>{Math.round(item.progress)}%</span>
            </div>
            <ProgressBar nProgress={item.progress} />
        </div>
        <DialogButton
            onClick={() => installQueue.cancelItem(item.shortname)}
            style={{
                width: '40px',
                minWidth: 'initial',
                padding: '8px',
                backgroundColor: '#8b1a1a',
            }}
        >
            <FaTimes style={{ verticalAlign: 'middle' }} />
        </DialogButton>
    </Focusable>
);

const QueuedItem: FC<{ item: QueueItem; isFirst: boolean; isLast: boolean }> = ({ item, isFirst, isLast }) => (
    <Focusable style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '10px 16px',
        backgroundColor: '#16161e',
        borderRadius: '6px',
        border: '1px solid #2a2a3a',
        marginBottom: '6px',
    }}>
        <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
                fontSize: '14px',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
            }}>
                {item.title}
            </div>
            <div style={{ fontSize: '11px', color: '#666' }}>
                Waiting...
            </div>
        </div>
        <Focusable style={{ display: 'flex', gap: '6px' }}>
            <DialogButton
                onClick={() => installQueue.moveUp(item.shortname)}
                disabled={isFirst}
                style={{
                    width: '36px',
                    minWidth: 'initial',
                    padding: '6px',
                    opacity: isFirst ? 0.3 : 1,
                }}
            >
                <FaArrowUp style={{ verticalAlign: 'middle', fontSize: '12px' }} />
            </DialogButton>
            <DialogButton
                onClick={() => installQueue.moveDown(item.shortname)}
                disabled={isLast}
                style={{
                    width: '36px',
                    minWidth: 'initial',
                    padding: '6px',
                    opacity: isLast ? 0.3 : 1,
                }}
            >
                <FaArrowDown style={{ verticalAlign: 'middle', fontSize: '12px' }} />
            </DialogButton>
            <DialogButton
                onClick={() => installQueue.remove(item.shortname)}
                style={{
                    width: '36px',
                    minWidth: 'initial',
                    padding: '6px',
                }}
            >
                <FaTimes style={{ verticalAlign: 'middle', fontSize: '12px' }} />
            </DialogButton>
        </Focusable>
    </Focusable>
);

const CompletedItem: FC<{ item: QueueItem }> = ({ item }) => (
    <Focusable style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '10px 16px',
        backgroundColor: '#0e1a0e',
        borderRadius: '6px',
        border: '1px solid #1a3a1a',
        marginBottom: '6px',
    }}>
        <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
                fontSize: '14px',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
            }}>
                {item.title}
            </div>
            <div style={{ fontSize: '11px', color: '#4caf50' }}>
                Installed
            </div>
        </div>
    </Focusable>
);

const ErrorItem: FC<{ item: QueueItem }> = ({ item }) => (
    <Focusable style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '10px 16px',
        backgroundColor: '#1a0e0e',
        borderRadius: '6px',
        border: '1px solid #3a1a1a',
        marginBottom: '6px',
    }}>
        <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
                fontSize: '14px',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
            }}>
                {item.title}
            </div>
            <div style={{ fontSize: '11px', color: '#ef5350' }}>
                {item.description}
            </div>
        </div>
        <DialogButton
            onClick={() => installQueue.remove(item.shortname)}
            style={{
                width: '36px',
                minWidth: 'initial',
                padding: '6px',
            }}
        >
            <FaTrash style={{ verticalAlign: 'middle', fontSize: '12px' }} />
        </DialogButton>
    </Focusable>
);
