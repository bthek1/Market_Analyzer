import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { getMe, login, logout, register } from "@/api/auth";
import { useAuthStore } from "@/store/auth";
import { queryKeys } from "@/api/queryKeys";
import type { RegisterRequest } from "@/types/auth";

export function useMe() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: getMe,
    enabled: isAuthenticated,
    retry: false,
  });
}

export function useLogin() {
  const { setAuth } = useAuthStore();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  return useMutation({
    mutationFn: async ({ email, password }: { email: string; password: string }) => {
      const response = await login(email, password);
      localStorage.setItem("access_token", response.access);
      localStorage.setItem("refresh_token", response.refresh);
      const me = await getMe();
      return { response, me };
    },
    onSuccess: ({ response, me }) => {
      setAuth(me, response.access, response.refresh);
      queryClient.setQueryData(queryKeys.auth.me(), me);
      navigate({ to: "/" });
    },
  });
}

export function useRegister() {
  const { setAuth } = useAuthStore();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  return useMutation({
    mutationFn: async (payload: RegisterRequest) => {
      const response = await register(payload);
      localStorage.setItem("access_token", response.access);
      localStorage.setItem("refresh_token", response.refresh);
      const me = await getMe();
      return { response, me };
    },
    onSuccess: ({ response, me }) => {
      setAuth(me, response.access, response.refresh);
      queryClient.setQueryData(queryKeys.auth.me(), me);
      navigate({ to: "/" });
    },
  });
}

export function useLogout() {
  const { clearAuth } = useAuthStore();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  return useMutation({
    mutationFn: logout,
    onSettled: () => {
      clearAuth();
      queryClient.clear();
      navigate({ to: "/login" });
    },
  });
}
