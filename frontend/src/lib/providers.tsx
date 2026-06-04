// app/providers.tsx
'use client'

import { useIsDarkMode } from "@/hooks/useDarkMode"

export function ThemeProvider({ children }: { children: React.ReactNode }) {
    useIsDarkMode();
    return <>{children}</>;
}
