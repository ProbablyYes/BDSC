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

  useEffect(() => {
    try {
      const raw = localStorage.getItem("va_user");
      if (raw) {
        const u: VaUser = JSON.parse(raw);
        if (requiredRole && u.role !== requiredRole) {
          router.replace("/auth/login");
          return;
        }
        setUser(u);
      } else {
        router.replace("/auth/login");
      }
    } catch {
      router.replace("/auth/login");
    }
    setChecked(true);
  }, [requiredRole, router]);

  return checked ? user : null;
}

export function logout() {
  localStorage.removeItem("va_user");
  window.location.href = "/auth/login";
}
