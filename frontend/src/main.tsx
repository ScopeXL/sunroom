import "./styles/tokens.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { startLanguage } from "./lib/lang";
import { noteScreenAgent } from "./lib/screenAgent";
import { startClock } from "./lib/time";
import { queryClient, router } from "./router";

// iOS Safari only shows :active (the press feedback, styles/motion.css) once a page listens for
// touches. Passive, so scrolling is never held up.
document.addEventListener("touchstart", () => undefined, { passive: true });
startClock();
// Before the router can change the address: a wall run by Sunroom Screen names its agent here.
noteScreenAgent(window.location.pathname, window.location.search);

const container = document.getElementById("root");
if (!container) throw new Error("The #root element is missing from index.html");

const app = container;
// The first paint is in the page's language (ADR 0043): another language's words are a chunk.
void startLanguage()
  .catch(() => undefined)
  .then(() => {
    createRoot(app).render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </StrictMode>,
    );
  });
