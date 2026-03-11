"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const STEPS = [
  {
    step: "1",
    title: "Install",
    code: "pip install retro-code",
  },
  {
    step: "2",
    title: "Set API Key",
    code: "export COMMONSTACK_API_KEY=your_key",
  },
  {
    step: "3",
    title: "Run",
    code: "retro --offline --dir .",
  },
];

const COMMANDS = [
  { cmd: "retro --offline --dir .", desc: "Run once, update rules, exit" },
  { cmd: "retro --up --dir .", desc: "Start background daemon" },
  { cmd: "retro --down --dir .", desc: "Stop daemon" },
  { cmd: "retro --hypogen --dir .", desc: "Find behavior patterns" },
  { cmd: "retro --monitor --port 8585", desc: "Start blast radius dashboard" },
  { cmd: "retro --submit --dir .", desc: "Submit discoveries to community" },
  { cmd: "retro --pull --dir .", desc: "Verify community hypotheses locally" },
];

export function GettingStarted() {
  return (
    <section id="getting-started" className="py-24">
      <div className="text-center mb-16 space-y-4">
        <h2 className="text-3xl font-bold tracking-tight sm:text-4xl font-heading">
          Get Started in 30 Seconds
        </h2>
        <p className="text-muted-foreground max-w-2xl mx-auto text-lg">
          Three commands. That&apos;s all it takes. RetroCode works with your
          existing agent setup out of the box.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-16">
        {STEPS.map((step) => (
          <Card key={step.step} className="text-center">
            <CardContent className="pt-6">
              <Badge className="mb-4">{`Step ${step.step}`}</Badge>
              <h3 className="text-lg font-semibold mb-3">{step.title}</h3>
              <code className="text-sm font-mono bg-muted px-3 py-2 rounded-lg block">
                {step.code}
              </code>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="max-w-3xl mx-auto">
        <h3 className="text-xl font-semibold mb-6 text-center font-heading">
          All Commands
        </h3>
        <Card>
          <CardContent className="pt-6">
            <div className="space-y-3 font-mono text-sm">
              {COMMANDS.map((item) => (
                <div
                  key={item.cmd}
                  className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4 py-2 border-b border-border last:border-0"
                >
                  <code className="text-foreground shrink-0">{item.cmd}</code>
                  <span className="text-muted-foreground text-xs sm:text-sm">
                    {item.desc}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
