import { cn } from "@/lib/utils";

export interface TabConfig {
  key: string;
  label: string;
}

interface CompanyTabsProps {
  tabs: TabConfig[];
  activeTab: string;
  onChange: (key: string) => void;
}

export function CompanyTabs({ tabs, activeTab, onChange }: CompanyTabsProps) {
  return (
    <div className="flex gap-1 border-b mb-6 overflow-x-auto">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={cn(
            "px-4 py-2 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors",
            activeTab === tab.key
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
