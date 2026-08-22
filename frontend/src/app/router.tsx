import { createBrowserRouter } from "react-router-dom";
import { Layout } from "./layout";
import { MePage } from "../features/me/MePage";

// Routes. The league page (`/leagues/:leagueSeasonId`) lands in S1-11b; the
// `/me` route here is the full vertical slice — generated client → typed fetch →
// token attach → react-query → render.
export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      {
        index: true,
        element: <MePage />,
      },
    ],
  },
]);
