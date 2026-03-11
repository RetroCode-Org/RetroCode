import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

const AGENTS = [
  {
    name: "Claude Code",
    file: "CLAUDE.md",
    color: "bg-[#D97757]/10 text-[#D97757] border-[#D97757]/30",
  },
  {
    name: "Cursor",
    file: ".cursor/rules/retro.mdc",
    color: "bg-[#4285F4]/10 text-[#4285F4] border-[#4285F4]/30",
  },
  {
    name: "Codex",
    file: "AGENTS.md",
    color: "bg-[#10A37F]/10 text-[#10A37F] border-[#10A37F]/30",
  },
];

const PROVIDERS = [
  { name: "CommonStack", note: "Free credits for members" },
  { name: "OpenAI", note: "" },
  { name: "Anthropic", note: "" },
  { name: "Google Gemini", note: "" },
  { name: "OpenRouter", note: "" },
];

export function CompatibilitySection() {
  return (
    <section className="py-24">
      <div className="text-center mb-16 space-y-4">
        <h2 className="text-3xl font-bold tracking-tight sm:text-4xl font-heading">
          Works With Your Stack
        </h2>
        <p className="text-muted-foreground max-w-2xl mx-auto text-lg">
          Read traces from any supported agent. Write rules to any output.
          Choose your LLM provider.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-4xl mx-auto">
        <Card>
          <CardContent className="pt-6">
            <h3 className="text-lg font-semibold mb-4">Agent Compatibility</h3>
            <div className="space-y-3">
              {AGENTS.map((agent) => (
                <div
                  key={agent.name}
                  className="flex items-center justify-between"
                >
                  <span className="font-medium">{agent.name}</span>
                  <Badge variant="outline" className={agent.color}>
                    {agent.file}
                  </Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <h3 className="text-lg font-semibold mb-4">LLM Providers</h3>
            <div className="space-y-3">
              {PROVIDERS.map((provider) => (
                <div
                  key={provider.name}
                  className="flex items-center justify-between"
                >
                  <span className="font-medium">{provider.name}</span>
                  {provider.note && (
                    <span className="text-xs text-muted-foreground">
                      {provider.note}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
