import { useMe } from "./queries";
import { Card } from "../../shared/ui/Card";
import { StateMessage } from "../../shared/ui/StateMessage";

export function MePage() {
  const { data, isPending, isError } = useMe();

  if (isPending) {
    return <StateMessage kind="loading" />;
  }
  if (isError) {
    return (
      <StateMessage
        kind="error"
        message="Could not load your profile. Check that a valid dev token is set."
      />
    );
  }

  return (
    <Card>
      <h2 className="text-xl font-semibold">{data.display_name}</h2>
      <p className="text-gray-600">{data.email}</p>
    </Card>
  );
}
