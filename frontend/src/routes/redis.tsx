import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";
import { RedisInfoCards } from "@/components/redis/RedisInfoCards";
import { RedisKeysTable } from "@/components/redis/RedisKeysTable";

export const Route = createFileRoute("/redis")({
  component: RedisPage,
});

const TABS = ["Server Info", "Keys"] as const;
type Tab = (typeof TABS)[number];

function RedisPage() {
  const [activeTab, setActiveTab] = useState<Tab>("Server Info");

  return (
    <AppShell>
      <h1 className="text-2xl font-semibold tracking-tight mb-6">Redis Monitor</h1>

      <div className="flex gap-1 border-b mb-6">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 transition-colors ${
              activeTab === tab
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "Server Info" && <RedisInfoCards />}
      {activeTab === "Keys" && <RedisKeysTable />}
    </AppShell>
  );
}
