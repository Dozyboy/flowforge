"use client";

import { useState } from "react";

import { useToast } from "@/components/ui/Toaster";
import { api, errorMessage } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";

export function EmailVerificationBanner() {
  const { me } = useAuth();
  const toast = useToast();
  const [sending, setSending] = useState(false);

  if (!me || me.user.is_email_verified) return null;

  const resend = async () => {
    setSending(true);
    try {
      await api("/auth/resend-verification", { method: "POST" });
      toast.success(`Verification email sent to ${me.user.email}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex items-center justify-center gap-2 bg-amber-50 px-4 py-2 text-sm text-amber-900">
      Please verify your email address.
      <button
        type="button"
        onClick={resend}
        disabled={sending}
        className="font-medium underline hover:no-underline disabled:opacity-60"
      >
        Resend email
      </button>
    </div>
  );
}
