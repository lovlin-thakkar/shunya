import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/layout/sidebar";
import { ApiKeyGate } from "@/components/api-key-gate";

export const metadata: Metadata = {
  title: "Shunya — Voice AI QA",
  description: "Automated voice AI quality assurance platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ApiKeyGate>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 overflow-y-auto min-w-0">
              {children}
            </main>
          </div>
        </ApiKeyGate>
      </body>
    </html>
  );
}
