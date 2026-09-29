import { DialogButton, Focusable, PanelSection, SteamSpinner, ToggleField } from "@decky/ui";
import { FC, useEffect, useState } from "react";
import { ScrollableWindowRelative } from "./ScrollableWindow";
import { executeAction } from "./Utils/executeAction";
import Logger from "./Utils/logger";
import { useTabVisibility } from "./hooks/useTabVisibility";
import { ActionSet, ContentResult, ContentType, ExecuteArgs, ExecuteGetContentArgs, StoreTabsContent, TabContent } from "./Types/Types";

/**
 * Show/hide toggles for the store tabs.
 *
 * Hiding is presentation only: nothing is logged out, uninstalled or removed.
 * A hidden store keeps its login, its installed games and its Steam shortcuts,
 * and simply stops taking a slot in the tab bar — which is the whole point on a
 * TV, where every extra tab is another R1 press.
 */
export const StoreTabsSettings: FC = () => {
    const logger = new Logger("StoreTabsSettings");
    const [tabs, setTabs] = useState<TabContent[] | null>(null);
    const [error, setError] = useState("");
    const { hidden, isHidden, setTabHidden, showAll } = useTabVisibility();

    useEffect(() => {
        (async () => {
            try {
                // The store tab bar is produced by the GameVaultActions set, which
                // MainMenu/GameVaultInit initialises. "init"/"InitActions" resolves
                // to the main menu instead and yields no tabs at all.
                const actionSetRes = await executeAction<ExecuteArgs, ActionSet>(
                    "MainMenu", "GameVaultInit", {});
                if (!actionSetRes) {
                    setError("Could not reach the plugin backend.");
                    return;
                }
                const contentRes = await executeAction<ExecuteGetContentArgs, ContentResult<ContentType>>(
                    actionSetRes.Content.SetName,
                    "GetContent",
                    {}
                );
                const found = (contentRes?.Content as unknown as StoreTabsContent)?.Tabs;
                setTabs(Array.isArray(found) ? found : []);
            } catch (caught) {
                logger.error("Loading store tabs: ", caught);
                setError(`${caught}`);
            }
        })();
    }, []);

    if (error) {
        return (
            <div style={{ padding: "0 15px" }}>
                <PanelSection title="Store Tabs">{error}</PanelSection>
            </div>
        );
    }

    if (tabs === null) return <SteamSpinner />;

    // The fallback in visibleTabs means this state is recoverable rather than
    // stuck, but say so plainly instead of letting the bar look broken.
    const allHidden = tabs.length > 0 && tabs.every((tab) => isHidden(tab.ActionId));

    return (
        <div style={{ padding: "0 15px", height: "100%", display: "flex" }}>
            <ScrollableWindowRelative>
                <PanelSection title="Store Tabs">
                    <div style={{ fontSize: "13px", color: "#8b929a", padding: "0 0 8px" }}>
                        Turn off the stores you do not use to keep them out of the tab bar. Hiding a
                        store does not log it out or remove anything — its games and Steam shortcuts
                        stay exactly as they are, and turning it back on restores the tab.
                    </div>

                    {tabs.length === 0 && <div>No store tabs found.</div>}

                    {tabs.map((tab) => (
                        <ToggleField
                            key={tab.ActionId}
                            label={tab.Title}
                            checked={!isHidden(tab.ActionId)}
                            onChange={(visible) => setTabHidden(tab.ActionId, !visible)}
                        />
                    ))}

                    {allHidden && (
                        <div style={{ fontSize: "13px", color: "#e3a74f", padding: "8px 0" }}>
                            Every store is hidden, so the tab bar is showing all of them instead.
                            Leave at least one turned on.
                        </div>
                    )}

                    {hidden.length > 0 && (
                        <Focusable style={{ padding: "10px 0" }}>
                            <DialogButton onClick={showAll}>Show all tabs</DialogButton>
                        </Focusable>
                    )}
                </PanelSection>
            </ScrollableWindowRelative>
        </div>
    );
};
