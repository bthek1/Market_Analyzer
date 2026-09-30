import { create } from "zustand";
import { immer } from "zustand/middleware/immer";

interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
}

interface AuthState {
  isAuthenticated: boolean;
  user: User | null;
  setAuth: (user: User, access: string, refresh: string) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>()(
  immer((set) => ({
    isAuthenticated: !!localStorage.getItem("access_token"),
    user: null,
    setAuth: (user, access, refresh) => {
      localStorage.setItem("access_token", access);
      localStorage.setItem("refresh_token", refresh);
      set((state) => {
        state.isAuthenticated = true;
        state.user = user;
      });
    },
    clearAuth: () => {
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
      set((state) => {
        state.isAuthenticated = false;
        state.user = null;
      });
    },
  }))
);
