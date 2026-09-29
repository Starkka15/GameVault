import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "GameVault_hiddenStoreTabs";

/**
 * Tabs are stored by the ActionId that produced them, never by title or by
 * position. Titles are display text and positions shift whenever an extension
 * is installed or removed, so either one would silently start hiding the wrong
 * store.
 *
 * Only hidden tabs are recorded. Anything absent from the list is visible,
 * which means an existing install changes nothing and a newly installed store —
 * ZOOM included, if it ever lands — shows up on its own rather than arriving
 * hidden and looking broken.
 */
export function readHiddenTabs(): string[] {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : [];
    } catch {
        // Corrupt or unavailable storage must not take the tab bar down with it.
        return [];
    }
}

function writeHiddenTabs(ids: string[]) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
        // Same-document storage events do not fire, so tell our own listeners.
        window.dispatchEvent(new CustomEvent(STORAGE_KEY));
    } catch {
        /* nothing useful to do if storage is full or blocked */
    }
}

export function useTabVisibility() {
    const [hidden, setHiddenState] = useState<string[]>(readHiddenTabs);

    // The About page and the tab bar are mounted at the same time, so a toggle
    // has to reach the bar without a reload.
    useEffect(() => {
        const sync = () => setHiddenState(readHiddenTabs());
        window.addEventListener(STORAGE_KEY, sync);
        window.addEventListener("storage", sync);
        return () => {
            window.removeEventListener(STORAGE_KEY, sync);
            window.removeEventListener("storage", sync);
        };
    }, []);

    const isHidden = useCallback((actionId: string) => hidden.includes(actionId), [hidden]);

    const setTabHidden = useCallback((actionId: string, hide: boolean) => {
        const next = hide
            ? [...new Set([...readHiddenTabs(), actionId])]
            : readHiddenTabs().filter((id) => id !== actionId);
        writeHiddenTabs(next);
        setHiddenState(next);
    }, []);

    const showAll = useCallback(() => {
        writeHiddenTabs([]);
        setHiddenState([]);
    }, []);

    return { hidden, isHidden, setTabHidden, showAll };
}

/**
 * Applies the hidden list to a set of tabs. Hiding every tab would leave an
 * empty bar with no way back to the settings that caused it, so an empty result
 * falls back to showing everything.
 */
export function visibleTabs<T extends { ActionId: string }>(tabs: T[], hidden: string[]): T[] {
    const kept = tabs.filter((tab) => !hidden.includes(tab.ActionId));
    return kept.length > 0 ? kept : tabs;
}
