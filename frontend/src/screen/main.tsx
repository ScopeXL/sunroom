import "../styles/tokens.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { startLanguage } from "../lib/lang";
import { noteOwnScreenAgent } from "../lib/screenAgent";
import { startClock } from "../lib/time";
import { ScreenApp } from "./ScreenApp";

// The pages' own agent serves them: every call goes to their own origin.
noteOwnScreenAgent();
document.addEventListener("touchstart", () => undefined, { passive: true });
startClock();

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

const container = document.getElementById("root");
if (!container) throw new Error("The #root element is missing from screen.html");

const app = container;
// The first paint is in the page's language (ADR 0043): another language's words are a chunk.
void startLanguage()
  .catch(() => undefined)
  .then(() => {
    createRoot(app).render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <ScreenApp />
        </QueryClientProvider>
      </StrictMode>,
    );
  });
