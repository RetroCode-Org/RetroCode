"use client";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  Github,
  Menu,
  Monitor,
  Moon,
  Sun,
} from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

function SlackIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" {...props}>
      <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.271 0a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.271a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zm10.124 2.521a2.528 2.528 0 0 1 2.52-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.52V8.834zm-1.271 0a2.528 2.528 0 0 1-2.521 2.521 2.528 2.528 0 0 1-2.521-2.521V2.522A2.528 2.528 0 0 1 15.166 0a2.528 2.528 0 0 1 2.521 2.522v6.312zm-2.521 10.124a2.528 2.528 0 0 1 2.521 2.52A2.528 2.528 0 0 1 15.166 24a2.528 2.528 0 0 1-2.521-2.522v-2.52h2.521zm0-1.271a2.528 2.528 0 0 1-2.521-2.521 2.528 2.528 0 0 1 2.521-2.521h6.312A2.528 2.528 0 0 1 24 15.166a2.528 2.528 0 0 1-2.522 2.521h-6.312z" />
    </svg>
  );
}

function DiscordIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" {...props}>
      <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515a.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0a12.64 12.64 0 0 0-.617-1.25a.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057a19.9 19.9 0 0 0 5.993 3.03a.078.078 0 0 0 .084-.028a14.09 14.09 0 0 0 1.226-1.994a.076.076 0 0 0-.041-.106a13.107 13.107 0 0 1-1.872-.892a.077.077 0 0 1-.008-.128a10.2 10.2 0 0 0 .372-.292a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127a12.299 12.299 0 0 1-1.873.892a.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028a19.839 19.839 0 0 0 6.002-3.03a.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419c0-1.333.955-2.419 2.157-2.419c1.21 0 2.176 1.096 2.157 2.419c0 1.334-.956 2.419-2.157 2.419zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419c0-1.333.955-2.419 2.157-2.419c1.21 0 2.176 1.096 2.157 2.419c0 1.334-.946 2.419-2.157 2.419z" />
    </svg>
  );
}

function RetroCodeLogo(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
      <line x1="12" y1="2" x2="12" y2="22" />
    </svg>
  );
}

export function Navbar() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [isScrolled, setIsScrolled] = useState(false);
  const [isScrollingDown, setIsScrollingDown] = useState(false);
  const lastScrollYRef = useRef(0);
  const pathname = usePathname();
  const shouldHideNavbar = isScrolled && isScrollingDown;

  useEffect(() => {
    setMounted(true);

    const handleScroll = () => {
      const currentScrollY = window.scrollY;
      const isPastThreshold = currentScrollY > 50;
      const didScrollDown =
        currentScrollY > lastScrollYRef.current && currentScrollY > 8;

      setIsScrolled(isPastThreshold);
      setIsScrollingDown(didScrollDown);
      lastScrollYRef.current = currentScrollY;
    };

    lastScrollYRef.current = window.scrollY;
    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();

    return () => window.removeEventListener("scroll", handleScroll);
  }, [pathname]);

  const navItems = [
    { href: "#features", label: "Features" },
    { href: "#how-it-works", label: "How It Works" },
    { href: "#getting-started", label: "Getting Started" },
    { href: "#community", label: "Community" },
  ];

  return (
    <nav
      className={cn(
        "z-50 flex items-center justify-between px-4 py-2 transition-[opacity,filter,background-color,border-color,transform] duration-300 ease-in-out",
        "fixed left-1/2 -translate-x-1/2 top-4",
        "w-[calc(100%-2rem)] max-w-5xl",
        "rounded-full border border-border",
        "bg-background/80 backdrop-blur-md supports-[backdrop-filter]:bg-background/60",
        shouldHideNavbar
          ? "opacity-0 blur-md pointer-events-none"
          : "opacity-100 blur-0",
      )}
    >
      <div className="flex items-center gap-2 font-bold hover:text-primary transition-colors group">
        <Link href="/" className="flex items-center gap-2">
          <RetroCodeLogo className="w-6 h-6" />
          <span className="hidden sm:inline-block tracking-tight">
            RetroCode
          </span>
        </Link>
      </div>

      <ul className="hidden lg:flex items-center gap-1">
        {navItems.map((item) => (
          <li key={item.href}>
            <Link
              href={item.href}
              className={cn(
                "text-sm font-medium transition-colors px-3 py-1.5 rounded-full hover:bg-muted/50",
                "text-muted-foreground hover:text-foreground",
              )}
            >
              {item.label}
            </Link>
          </li>
        ))}
      </ul>

      <div className="flex items-center gap-2 pl-2">
        {mounted && (
          <>
            <div className="hidden lg:flex items-center bg-muted/50 rounded-full border border-border/40 p-0.5">
              {[
                { name: "light", icon: Sun },
                { name: "dark", icon: Moon },
                { name: "system", icon: Monitor },
              ].map((mode) => (
                <Button
                  key={mode.name}
                  onClick={() => setTheme(mode.name)}
                  variant="ghost"
                  size="icon"
                  className={cn(
                    "h-7 w-7",
                    theme === mode.name
                      ? "bg-background text-foreground hover:bg-background shadow-sm"
                      : "text-muted-foreground hover:text-foreground hover:bg-transparent",
                  )}
                  aria-label={`Switch to ${mode.name} mode`}
                >
                  <mode.icon className="w-3.5 h-3.5" aria-hidden="true" />
                </Button>
              ))}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden h-8 w-8"
              onClick={() => {
                const next =
                  theme === "light"
                    ? "dark"
                    : theme === "dark"
                      ? "system"
                      : "light";
                setTheme(next);
              }}
              aria-label="Toggle theme"
            >
              {theme === "light" ? (
                <Sun className="w-4 h-4" aria-hidden="true" />
              ) : theme === "dark" ? (
                <Moon className="w-4 h-4" aria-hidden="true" />
              ) : (
                <Monitor className="w-4 h-4" aria-hidden="true" />
              )}
            </Button>
          </>
        )}

        <div className="flex items-center gap-1 border-l border-border/40 pl-2 ml-1">
          <Button
            variant="ghost"
            size="icon"
            asChild
            className="h-8 w-8"
            aria-label="Slack"
          >
            <a href="https://join.slack.com/t/retrocode-workspace/shared_invite/zt-3s4qb61lg-WH3V_3K0i4fe97tJed8Icw">
              <SlackIcon className="w-4 h-4" aria-hidden="true" />
            </a>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            asChild
            className="h-8 w-8"
            aria-label="Discord"
          >
            <a href="https://discord.gg/CFEcwyWC">
              <DiscordIcon className="w-4 h-4" aria-hidden="true" />
            </a>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            asChild
            className="h-8 w-8"
            aria-label="GitHub"
          >
            <a href="https://github.com/RetroCode-Org/RetroCode">
              <Github className="w-4 h-4" aria-hidden="true" />
            </a>
          </Button>
        </div>

        <div className="lg:hidden ml-1">
          <Popover open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Toggle menu">
                <Menu className="w-4 h-4" aria-hidden="true" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-48 p-2 rounded-xl" align="end">
              <div className="flex flex-col gap-1">
                {navItems.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMobileMenuOpen(false)}
                    className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors px-3 py-2 rounded-lg hover:bg-muted/50"
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </div>
    </nav>
  );
}
