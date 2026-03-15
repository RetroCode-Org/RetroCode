import { HomeBackground } from "@/components/HomeBackground";
import { HowItWorks } from "@/components/HowItWorks";
import { FeatureCards } from "@/components/FeatureCards";
import { GettingStarted } from "@/components/GettingStarted";
import { CompatibilitySection } from "@/components/CompatibilitySection";
import { CommunitySection } from "@/components/CommunitySection";
import { Button } from "@/components/ui/button";
import Image from "next/image";
import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-col min-h-screen relative text-foreground overflow-x-hidden">
      <main className="flex-1">
        {/* Hero Section */}
        <div className="flex flex-col items-center justify-center min-h-[75vh] text-center space-y-8 relative z-10 px-4 pt-20 overflow-hidden">
          <HomeBackground />
          <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-3xl h-full max-h-128 bg-background/60 blur-hero -z-10 rounded-full pointer-events-none mix-blend-normal" />

          <div className="space-y-6">
            <Image
              src="/banner.png"
              alt="RetroCode"
              width={600}
              height={150}
              className="mx-auto drop-shadow-2xl rounded-lg"
              priority
            />

            <h1 className="text-2xl sm:text-3xl lg:text-4xl font-medium tracking-tight text-foreground leading-tight drop-shadow-2xl max-w-3xl mx-auto">
              Turn Agent Traces Into
              <br />
              <span className="text-muted-foreground">Auto-Updating Playbooks</span>
            </h1>

            <p className="max-w-xl mx-auto text-lg text-foreground/80 font-normal drop-shadow-md">
              RetroCode reads your AI coding agent sessions and generates
              project-specific rules, statistical insights, and blast radius
              analysis -- automatically.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-6 pt-4">
            <Button asChild>
              <Link href="#getting-started">
                Get Started
              </Link>
            </Button>
            <Button
              asChild
              variant="secondary"
              className="border border-border hover:bg-accent transition-colors"
            >
              <a href="https://github.com/Hanchenli/RetroCode">
                View on GitHub
              </a>
            </Button>
            <Button
              asChild
              variant="secondary"
              className="border border-border hover:bg-accent transition-colors"
            >
              <Link href="#features">
                Learn More
              </Link>
            </Button>
          </div>
        </div>

        <HowItWorks />

        <div className="max-w-6xl mx-auto px-4 md:px-8 py-12 space-y-0">
          <FeatureCards />
          <GettingStarted />
          <CompatibilitySection />
          <CommunitySection />
        </div>
      </main>
    </div>
  );
}
