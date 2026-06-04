import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "../globals.css";
import { AppSidebar } from "@/components/AppSidebar";
import { CostBadge } from "@/components/CostBadge";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { AuthProvider } from "@/lib/auth";

import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "@/lib/providers";
import { SidebarController } from "@/components/utils/SidebarAutoCollapse";
// import Image from "next/image";
import Link from "next/link";

const geistSans = Geist({
    variable: "--font-geist-sans",
    subsets: ["latin"],
});

const geistMono = Geist_Mono({
    variable: "--font-geist-mono",
    subsets: ["latin"],
});

export const metadata: Metadata = {
    title: "DeepRead",
    description: "Personal literature reading workstation — read, annotate, and understand your papers.",
    icons: {
        icon: "/icon.svg"
    },
};

export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="en" suppressHydrationWarning>
            <head>
                <script
                    id="theme-script"
                    dangerouslySetInnerHTML={{
                        __html: `
      try {
        if (localStorage.getItem('darkMode') === 'dark' ||
            (!localStorage.getItem('darkMode') && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
          document.documentElement.classList.add('dark');
        } else {
          document.documentElement.classList.remove('dark');
        }
      } catch (e) {}
    `,
                    }}
                />
            </head>
            <body
                className={`${geistSans.variable} ${geistMono.variable} antialiased`}
            >
                <ThemeProvider>
                    <AuthProvider>
                        <SidebarProvider>
                                <AppSidebar />
                                <SidebarInset>
                                    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
                                        <SidebarTrigger className="-ml-1" />
                                        <Separator orientation="vertical" className="mr-2 h-4" />
                                        <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
                                            <span className="text-sm font-semibold">DeepRead</span>
                                        </Link>
                                        <div className="flex-1" />
                                        <CostBadge />
                                    </header>
                                    <SidebarController>
                                        {children}
                                    </SidebarController>
                                </SidebarInset>
                            </SidebarProvider>
                    </AuthProvider>
                </ThemeProvider>
                <Toaster
                    position="top-right"
                    richColors
                    duration={3000}
                />
            </body>
        </html>
    );
}
