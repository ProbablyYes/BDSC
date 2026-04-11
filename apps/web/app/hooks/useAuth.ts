"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export interface VaUser {
  user_id: string;
  role: "student" | "teacher" | "admin";
  display_name: string;
  email: string;
  student_id?: string;
  class_id?: string;
  cohort_id?: string;
  bio?: string;
  created_at?: string;
}

/**
 * Returns the logged-in user or `null` while checking.
 * If `requiredRole` is set and the current user's role doesn't match,
 * or if no user is logged in, it redirects to /auth/login.
 */
export function useAuth(requiredRole?: string): VaUser | null {
  const router = useRouter();
  const [user, setUser] = useState<VaUser | null>(null);
  const [checked, setChecked] = useState(false);

  const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

  function logUnauthorizedAttempt(currentUser: VaUser | null, reason: string) {
    try {
      if (!requiredRole) return;
      const payload: any = {
        reason,
        role: currentUser?.role ?? undefined,
        user_id: currentUser?.user_id ?? undefined,
        display_name: currentUser?.display_name ?? undefined,
        path: typeof window !== "undefined" ? window.location.pathname : undefined,
      };
      // Fire-and-forget; logging failures must not block navigation.
      fetch(`${API_BASE}/api/admin/logs/unauthorized`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => {});
    } catch {
      // Swallow any logging errors to avoid breaking UX.
    }
  }

  useEffect(() => {
    try {
      const raw = localStorage.getItem("va_user");
      if (raw) {
        const u: VaUser = JSON.parse(raw);
        if (requiredRole && u.role !== requiredRole) {
          logUnauthorizedAttempt(u, "role_mismatch");
          router.replace("/auth/login");
          return;
        }
        setUser(u);
      } else {
        if (requiredRole) {
          logUnauthorizedAttempt(null, "no_user");
        }
        router.replace("/auth/login");
        return;
      }
    } catch {
      if (requiredRole) {
        logUnauthorizedAttempt(null, "parse_error");
      }
      router.replace("/auth/login");
      return;
    }
    setChecked(true);
  }, [requiredRole, router]);

  return checked ? user : null;
}

export function logout() {
  localStorage.removeItem("va_user");
  window.location.href = "/auth/login";
}
