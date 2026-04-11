"use client";

import { useParams } from "next/navigation";
import { useAuth } from "../../hooks/useAuth";
import BudgetWorkbench from "../BudgetContent";

export default function BudgetPlanPage() {
  const user = useAuth();
  const params = useParams();
  const planId = params?.planId as string;

  if (!user || !planId) return <div className="bw-page"><div className="bw-loading-center">加载中...</div></div>;

  return (
    <div className="bw-page">
      <BudgetWorkbench userId={user.user_id} planId={planId} />
    </div>
  );
}
