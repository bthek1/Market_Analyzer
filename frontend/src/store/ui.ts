import { create } from "zustand";
import { immer } from "zustand/middleware/immer";

const STORAGE_KEY = "sidebar_collapsed";

interface UIState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
}

function persist(collapsed: boolean) {
  localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
}

export const useUIStore = create<UIState>()(
  immer((set) => ({
    sidebarCollapsed: localStorage.getItem(STORAGE_KEY) === "1",
    toggleSidebar: () =>
      set((state) => {
        state.sidebarCollapsed = !state.sidebarCollapsed;
        persist(state.sidebarCollapsed);
      }),
    setSidebarCollapsed: (collapsed) =>
      set((state) => {
        state.sidebarCollapsed = collapsed;
        persist(collapsed);
      }),
  }))
);
