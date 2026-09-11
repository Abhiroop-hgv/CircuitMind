/**
 * Deprecated. Sign-in now lives as the final scene of the scroll landing at
 * /welcome — there is no standalone sign-in page. This route stays only to
 * redirect any old link or bookmark.
 */

import { redirect } from "next/navigation";

export default function LoginPage() {
  redirect("/welcome");
}
