import { createBrowserRouter } from "react-router-dom";
import { Layout } from "./layout";
import { MePage } from "../features/me/MePage";
import { LeaguePage } from "../features/standings/LeaguePage";

// Routes. The `/me` route is the full vertical slice from S1-11a; the league
// page (S1-11b) renders standings for a league season reached by UUID.
export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      {
        index: true,
        element: <MePage />,
      },
      {
        path: "leagues/:leagueSeasonId",
        element: <LeaguePage />,
      },
    ],
  },
]);
