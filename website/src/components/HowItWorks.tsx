import { cn } from "@/lib/utils";

const STEPS = [
  {
    id: "ingest",
    title: "1. Ingest Traces",
    description:
      "RetroCode reads session traces from Claude Code, Cursor, and Codex. It parses conversations into structured rounds, tracking every tool call, edit, and decision the agent made.",
    dotColor: "bg-[#3BB89E]",
  },
  {
    id: "reflect",
    title: "2. Reflect & Curate",
    description:
      "Each session is analyzed individually by a Reflector that extracts patterns, mistakes, and strategies. A Curator then synthesizes insights across all sessions, adding, modifying, or removing playbook bullets.",
    dotColor: "bg-[#C4B5A3]",
  },
  {
    id: "playbook",
    title: "3. Update Playbook",
    description:
      "The curated insights are written back into your agent's config file (CLAUDE.md, .cursor/rules, or AGENTS.md) between safe markers. Your agent gets smarter with every session, automatically.",
    dotColor: "bg-[#D08050]",
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="py-24 relative overflow-hidden">
      <div className="container px-4 md:px-6 mx-auto">
        <div className="text-center mb-16 space-y-4">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl font-heading">
            How RetroCode Works
          </h2>
          <p className="text-muted-foreground max-w-2xl mx-auto text-lg">
            A three-stage pipeline that turns raw agent conversations into
            actionable project-specific rules.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-center max-w-5xl mx-auto">
          {/* Visual Diagram */}
          <div className="relative flex items-center justify-center select-none">
            <div className="relative w-[280px] h-[280px] sm:w-[320px] sm:h-[320px] md:w-[360px] md:h-[360px]">
              {/* Outer ring - Ingest */}
              <div
                className="absolute inset-0 rounded-full flex items-start justify-center bg-[#3BB89E] dark:bg-[#2A9A82]"
                style={{ paddingTop: "8%" }}
              >
                <div className="text-center">
                  <span className="block font-bold text-base sm:text-lg text-[#0D3D34] dark:text-[#D4F5ED]">
                    Ingest
                  </span>
                  <span className="block text-xs sm:text-sm font-medium text-[#0D3D34]/60 dark:text-[#D4F5ED]/60">
                    Traces
                  </span>
                </div>
              </div>

              {/* Middle ring - Reflect */}
              <div className="absolute left-1/2 bottom-0 -translate-x-1/2 w-[200px] h-[200px] sm:w-[235px] sm:h-[235px] md:w-[260px] md:h-[260px] rounded-full bg-background z-10">
                <div
                  className="w-full h-full rounded-full flex items-start justify-center bg-[#C4B5A3] dark:bg-[#8A7D6D]"
                  style={{ paddingTop: "8%" }}
                >
                  <div className="text-center">
                    <span className="block font-bold text-sm sm:text-base text-[#3D3329] dark:text-[#E8DDD0]">
                      Reflect
                    </span>
                    <span className="block text-xs sm:text-sm font-medium text-[#3D3329]/60 dark:text-[#E8DDD0]/60">
                      Analyze
                    </span>
                  </div>
                </div>
              </div>

              {/* Inner circle - Playbook */}
              <div className="absolute left-1/2 bottom-0 -translate-x-1/2 w-[130px] h-[130px] sm:w-[155px] sm:h-[155px] md:w-[170px] md:h-[170px] rounded-full bg-background z-20">
                <div className="w-full h-full rounded-full flex items-center justify-center bg-[#D08050] dark:bg-[#B06838]">
                  <div className="text-center">
                    <span className="block font-bold text-sm sm:text-base text-[#3D1F0D] dark:text-[#FFE0CC]">
                      Playbook
                    </span>
                    <span className="block text-xs sm:text-sm font-medium text-[#3D1F0D]/60 dark:text-[#FFE0CC]/60">
                      Rules
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Legend / Steps */}
          <div className="space-y-2">
            {STEPS.map((step, index) => (
              <div
                key={step.id}
                className="flex gap-2 rounded-xl py-4 px-4"
              >
                <div className="flex flex-col items-center pt-1.5 shrink-0">
                  <div
                    className={cn(
                      "h-4 w-4 rounded-full ring-2 ring-background",
                      step.dotColor
                    )}
                  />
                  {index !== STEPS.length - 1 && (
                    <div className="w-px flex-1 bg-border mt-2" />
                  )}
                </div>

                <div className="space-y-2">
                  <h3 className="text-xl font-semibold font-heading">
                    {step.title}
                  </h3>
                  <p className="text-muted-foreground leading-relaxed">
                    {step.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
