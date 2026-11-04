"use client";

import { createClient } from "@/lib/supabase/client";
import { consumeReturnPath } from "@/lib/returnTo";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function CallbackPage() {
  const router = useRouter();

  useEffect(() => {
    // The browser client exchanges ?code= during init; getSession waits for that to finish.
    createClient().auth.getSession().then(({ data: { session } }) => {
      router.replace(session ? consumeReturnPath() : "/login");
    });
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-muted-foreground">Completing sign in...</p>
    </div>
  );
}
