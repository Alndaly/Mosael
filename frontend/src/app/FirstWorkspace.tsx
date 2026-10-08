import React from "react";
import { FolderPlus } from "lucide-react";

import { useAuth } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { isImeKeystroke } from "@/lib/shortcuts";

/**
 * 第一次进来、还没有任何工作区:建一个,**名字自己起**(预填「{昵称}的工作区」)。此前只有一个「创建默认工作区」,
 * 每个新用户的第一个工作区都叫「默认工作区」—— 被拉进团队后切换器里两行同名,分不清哪个是团队的(体检 UM-10)。
 */
export function FirstWorkspace({ pending, onCreate }: { pending: boolean; onCreate: (name: string) => void }) {
  const t = useI18n();
  const { user } = useAuth();
  const [name, setName] = React.useState(() =>
    user?.display_name || user?.username ? t("workspaceDefaultFor").replace("{name}", user.display_name || user.username) : t("workspaceDefault"),
  );
  const submit = () => {
    if (name.trim()) onCreate(name.trim());
  };
  return (
    <Card className="w-[min(480px,calc(100vw-32px))] border-0 bg-transparent shadow-none">
      <CardContent className="grid justify-items-start gap-6 px-7 py-10 text-left [&_h1]:m-0 [&_p]:m-0">
        <h1 className="text-4xl font-semibold tracking-tighter">Mosael</h1>
        <p className="text-lg leading-relaxed text-muted-foreground">{t("welcomeText")}</p>
        <label className="grid w-full gap-1.5 text-ui-sm font-medium text-foreground">
          <span>{t("workspaceNameLabel")}</span>
          <Input
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !isImeKeystroke(event)) submit();
            }}
          />
        </label>
        <Button loading={pending} disabled={!name.trim()} onClick={submit}>
          <FolderPlus size={16} /> {t("createWorkspace")}
        </Button>
      </CardContent>
    </Card>
  );
}
