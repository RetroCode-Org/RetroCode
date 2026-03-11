import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  BookOpen,
  FlaskConical,
  Activity,
  Terminal,
  Users,
  Layers,
} from "lucide-react";

const FEATURES = [
  {
    icon: BookOpen,
    title: "Auto-Updating Playbooks",
    description:
      "Automatically generates and maintains project-specific rules from your agent sessions. The more you use your agent, the smarter it gets.",
    badge: "Core",
  },
  {
    icon: FlaskConical,
    title: "Hypothesis Generation",
    description:
      "Statistically identifies behavior patterns that predict user rejection using chi-squared tests and odds ratios. Discover why your agent fails.",
    badge: "Analytics",
  },
  {
    icon: Activity,
    title: "Blast Radius Monitoring",
    description:
      "Web dashboard that estimates code edit impact by building dependency graphs and classifying files by risk tier.",
    badge: "Monitoring",
  },
  {
    icon: Layers,
    title: "Multi-Agent Support",
    description:
      "Ingests traces from Claude Code, Cursor, and Codex. Outputs rules to any configured agent's config file seamlessly.",
    badge: "Integration",
  },
  {
    icon: Terminal,
    title: "Simple CLI",
    description:
      "One command to start. Run as a background daemon or one-shot. Supports offline mode, YAML config, and flexible provider selection.",
    badge: "Developer Experience",
  },
  {
    icon: Users,
    title: "Community Hypotheses",
    description:
      "Submit discoveries, pull community-verified patterns, and contribute verification stats. Learn from every developer's agent experience.",
    badge: "Community",
  },
];

export function FeatureCards() {
  return (
    <section id="features" className="py-24">
      <div className="text-center mb-16 space-y-4">
        <h2 className="text-3xl font-bold tracking-tight sm:text-4xl font-heading">
          Everything You Need to Improve Your Agent
        </h2>
        <p className="text-muted-foreground max-w-2xl mx-auto text-lg">
          Three powerful capabilities that work together to make your AI coding
          agent learn from experience.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {FEATURES.map((feature) => (
          <Card
            key={feature.title}
            className="group hover:border-foreground/20 transition-colors"
          >
            <CardHeader>
              <div className="flex items-center justify-between mb-2">
                <feature.icon className="w-8 h-8 text-muted-foreground group-hover:text-foreground transition-colors" />
                <Badge variant="secondary" className="text-xs">
                  {feature.badge}
                </Badge>
              </div>
              <CardTitle className="text-lg">{feature.title}</CardTitle>
            </CardHeader>
            <CardContent>
              <CardDescription className="text-sm leading-relaxed">
                {feature.description}
              </CardDescription>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
