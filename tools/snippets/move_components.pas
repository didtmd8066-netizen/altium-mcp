// 부품을 목록대로 옮긴다 (회전·면은 그대로). 한 번의 실행이 Undo 1회로 묶인다.
// 직접 붙여 넣지 말고 `tools/plan_script.py moves` (또는 MCP 도구 apply_component_moves) 로 조립한다.
//
// {MOVES}: 한 줄에 부품 하나   지정자|새 x mm|새 y mm|지금 x um|지금 y um|겹침(0/1)
// "지금 좌표" 가 덤프 때와 0.02mm 넘게 다르면 그 부품은 건너뛴다 - 덤프 뒤에 사용자가 옮긴 부품이다.
// 지정자가 겹치는 부품(R? Q?, 겹침 = 1)은 이름으로 못 찾으므로 보드를 훑어 이름 + 지금 좌표로 찾는다.
// 겹치지 않는 부품은 훑지 않는다 - 좌표가 안 맞는다고 매번 훑으면 부품 수의 제곱이 되어, 목록 전체가
// 어긋난 경우(같은 목록을 두 번 적용) 제한 시간을 넘긴다.
// Component.MoveToXY 는 패드·바디·실크를 함께 옮긴다 (PlaceComponentsFromList 와 같은 방식).
{BOARD}
if Brd1 = nil then ResultText := 'NO BOARD'
else
begin
List1.LoadFromFile('{MOVES}');
PCBServer.PreProcess;
I2 := 0;
I3 := 0;
S4 := '';
for I1 := 0 to List1.Count - 1 do
begin
  S1 := List1[I1];
  B1 := Pos('|', S1);
  if B1 > 0 then
  begin
    S2 := Copy(S1, 1, B1 - 1);
    S1 := Copy(S1, B1 + 1, 200);
    B1 := Pos('|', S1);
    Obj3 := Copy(S1, 1, B1 - 1);
    S1 := Copy(S1, B1 + 1, 200);
    B1 := Pos('|', S1);
    Obj4 := Copy(S1, 1, B1 - 1);
    S1 := Copy(S1, B1 + 1, 200);
    B1 := Pos('|', S1);
    S3 := Copy(S1, 1, B1 - 1);
    S1 := Copy(S1, B1 + 1, 200);
    B1 := Pos('|', S1);
    Obj6 := '0';
    if B1 > 0 then
    begin
      Obj6 := Copy(S1, B1 + 1, 10);
      S1 := Copy(S1, 1, B1 - 1);
    end;
    Obj5 := nil;
    Obj2 := Brd1.GetPcbComponentByRefDes(S2);
    if Obj2 <> nil then
      if (Abs(Round(CoordToMMs(Obj2.x - Brd1.XOrigin)*1000) - StrToInt(S3)) <= 20) and (Abs(Round(CoordToMMs(Obj2.y - Brd1.YOrigin)*1000) - StrToInt(S1)) <= 20) then Obj5 := Obj2;
    if (Obj5 = nil) and (Obj6 = '1') then
    begin
      Obj1 := Brd1.BoardIterator_Create;
      Obj1.AddFilter_ObjectSet(MkSet(eComponentObject));
      Obj1.AddFilter_LayerSet(AllLayers);
      Obj1.AddFilter_Method(eProcessAll);
      Obj2 := Obj1.FirstPCBObject;
      while Obj2 <> nil do
      begin
        if (Obj2.Name.Text = S2) and (Abs(Round(CoordToMMs(Obj2.x - Brd1.XOrigin)*1000) - StrToInt(S3)) <= 20) and (Abs(Round(CoordToMMs(Obj2.y - Brd1.YOrigin)*1000) - StrToInt(S1)) <= 20) then
        begin
          Obj5 := Obj2;
          Obj2 := nil;
        end
        else Obj2 := Obj1.NextPCBObject;
      end;
      Brd1.BoardIterator_Destroy(Obj1);
    end;
    if Obj5 = nil then
    begin
      I3 := I3 + 1;
      if Length(S4) < 120 then S4 := S4 + S2 + ' ';
    end
    else
    begin
      PCBServer.SendMessageToRobots(Obj5.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);
      Obj5.MoveToXY(MMsToCoord(StrToFloat(Obj3)) + Brd1.XOrigin, MMsToCoord(StrToFloat(Obj4)) + Brd1.YOrigin);
      PCBServer.SendMessageToRobots(Obj5.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);
      I2 := I2 + 1;
    end;
  end;
end;
PCBServer.PostProcess;
Brd1.ViewManager_FullUpdate;
if S4 <> '' then SandboxLog('skipped: ' + S4);
ResultText := 'moved ' + IntToStr(I2) + ' / skipped ' + IntToStr(I3) + ' | ' + ExtractFileName(Brd1.FileName);
end;
