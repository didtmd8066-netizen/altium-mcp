// route_lib.py 가 만든 계획을 보드에 적용한다. 한 번의 실행이 Undo 1회로 묶인다.
// 직접 붙여 넣지 말고 `tools/plan_script.py` (또는 MCP 도구 apply_plan) 로 조립해서 쓴다 -
// 아래 //## 표시가 블록 경계이고, {..} 자리를 그쪽에서 채운다.
//
// {DEL}: 한 줄에 키 하나 (um 정수). route_lib.write_plan 이 반올림 경계값은 양쪽 다 넣어 준다.
//   T,x1,y1,x2,y2   A,cx,cy,r   V,x,y
// {NEW}: 한 객체당 8줄, 넷 이름 순 (넷 조회를 넷 종류 수만큼으로 줄이려고)
//   넷 / T / x1 / y1 / x2 / y2 / 층 / 폭
//   넷 / A / cx / cy / 반지름 / 시작각 / 끝각 / 층:폭
//   넷 / V / x / y / 견본x_um / 견본y_um / - / -
//   넷 / V / x / y / - / - / size / hole          견본 없음: 기본 via 로 만들고 선택해 둔다 (텐팅은 사용자가 체크)
//
// 비아는 견본 비아(좌표로 지정)를 Replicate 해서 만든다. 텐팅은 스크립트로 못 켜므로
// 사용자가 쓰던 비아를 복제해야 텐팅·크기가 따라온다. 같은 견본이 이어지면 다시 찾지 않는다.
// 넷은 생성 시점에 넣는다 (기존 객체에 Obj.Net := 는 반영되지 않는다).
//
// 순서는 조립할 때 정한다.
//   생성 -> 삭제 (기본)  비아를 "옮길" 때 옮길 비아를 견본으로 삼을 수 있다 (생성 시점에 견본이 살아 있다).
//                        새 객체와 삭제 키가 같은 좌표면 만든 직후 지워진다 - route_lib.write_plan 이 막는다.
//   삭제 -> 생성          같은 자리에 넷만 바꿔 다시 만들 때 (mirror_board.py). 견본은 지워지지 않는 비아여야 한다.
//
// 삭제는 한 번 순회하며 OList1 에 모으고, iterator 를 닫은 뒤 지운다 (순회 중에 지우면 안 된다).
// 예전에는 하나 지울 때마다 처음부터 다시 돌아서 수백 개를 지우면 제한 시간을 넘겼다.
// 모인 개수가 {MAXDEL} 을 넘으면 계획과 보드가 어긋난 것이므로 하나도 지우지 않는다.
//
// 스크래치 변수: S1~S4, I1~I3, B1, Obj1~Obj6, List1, OList1, Brd1 (Sandbox.template.pas).
//## HEAD
{BOARD}
if Brd1 = nil then ResultText := 'NO BOARD'
else
begin
PCBServer.PreProcess;
I3 := 0;
I2 := 0;
//## CREATE
List1.Sorted := False;
List1.LoadFromFile('{NEW}');
S3 := '';
S4 := '';
Obj5 := nil;
Obj6 := nil;
I1 := 0;
B1 := 0;
while I1 + 7 < List1.Count do
begin
  S2 := List1[I1];
  if S2 <> S3 then
  begin
    Obj5 := nil;
    Obj1 := Brd1.BoardIterator_Create;
    Obj1.AddFilter_ObjectSet(MkSet(eNetObject));
    Obj1.AddFilter_LayerSet(AllLayers);
    Obj1.AddFilter_Method(eProcessAll);
    Obj2 := Obj1.FirstPCBObject;
    while Obj2 <> nil do
    begin
      if Obj2.Name = S2 then begin Obj5 := Obj2; Obj2 := nil; end
      else Obj2 := Obj1.NextPCBObject;
    end;
    Brd1.BoardIterator_Destroy(Obj1);
    S3 := S2;
    if (Obj5 = nil) and (S2 <> '-') then SandboxLog('NO NET ' + S2);
  end;
  S1 := List1[I1+1];
  Obj4 := nil;
  if (S1 = 'V') and (List1[I1+4] = '-') then
  begin
    Obj4 := PCBServer.PCBObjectFactory(eViaObject, eNoDimension, eCreate_Default);
    Obj4.Size := MMsToCoord(StrToFloat(List1[I1+6]));
    Obj4.HoleSize := MMsToCoord(StrToFloat(List1[I1+7]));
    Obj4.LowLayer := eTopLayer;
    Obj4.HighLayer := eBottomLayer;
    Obj4.x := MMsToCoord(StrToFloat(List1[I1+2])) + Brd1.XOrigin;
    Obj4.y := MMsToCoord(StrToFloat(List1[I1+3])) + Brd1.YOrigin;
    B1 := 2;
  end
  else if S1 = 'V' then
  begin
    if (Obj6 = nil) or (S4 <> List1[I1+4] + ',' + List1[I1+5]) then
    begin
      Obj6 := nil;
      S4 := List1[I1+4] + ',' + List1[I1+5];
      Obj1 := Brd1.BoardIterator_Create;
      Obj1.AddFilter_ObjectSet(MkSet(eViaObject));
      Obj1.AddFilter_LayerSet(AllLayers);
      Obj1.AddFilter_Method(eProcessAll);
      Obj2 := Obj1.FirstPCBObject;
      while Obj2 <> nil do
      begin
        if (Abs(Round(CoordToMMs(Obj2.x - Brd1.XOrigin)*1000) - StrToInt(List1[I1+4])) <= 2) and (Abs(Round(CoordToMMs(Obj2.y - Brd1.YOrigin)*1000) - StrToInt(List1[I1+5])) <= 2) then begin Obj6 := Obj2; Obj2 := nil; end
        else Obj2 := Obj1.NextPCBObject;
      end;
      Brd1.BoardIterator_Destroy(Obj1);
    end;
    if Obj6 = nil then SandboxLog('NO VIA TEMPLATE ' + S4)
    else
    begin
      Obj4 := Obj6.Replicate;
      Obj4.Selected := False;
      Obj4.x := MMsToCoord(StrToFloat(List1[I1+2])) + Brd1.XOrigin;
      Obj4.y := MMsToCoord(StrToFloat(List1[I1+3])) + Brd1.YOrigin;
    end;
  end
  else if S1 = 'A' then
  begin
    S1 := List1[I1+7];
    B1 := Pos(':', S1);
    Obj4 := PCBServer.PCBObjectFactory(eArcObject, eNoDimension, eCreate_Default);
    Obj4.XCenter := MMsToCoord(StrToFloat(List1[I1+2])) + Brd1.XOrigin;
    Obj4.YCenter := MMsToCoord(StrToFloat(List1[I1+3])) + Brd1.YOrigin;
    Obj4.Radius := MMsToCoord(StrToFloat(List1[I1+4]));
    Obj4.StartAngle := StrToFloat(List1[I1+5]);
    Obj4.EndAngle := StrToFloat(List1[I1+6]);
    Obj4.Layer := String2Layer(Copy(S1, 1, B1 - 1));
    Obj4.LineWidth := MMsToCoord(StrToFloat(Copy(S1, B1 + 1, 20)));
    B1 := 0;
  end
  else
  begin
    Obj4 := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
    Obj4.Layer := String2Layer(List1[I1+6]);
    Obj4.Width := MMsToCoord(StrToFloat(List1[I1+7]));
    Obj4.X1 := MMsToCoord(StrToFloat(List1[I1+2])) + Brd1.XOrigin;
    Obj4.Y1 := MMsToCoord(StrToFloat(List1[I1+3])) + Brd1.YOrigin;
    Obj4.X2 := MMsToCoord(StrToFloat(List1[I1+4])) + Brd1.XOrigin;
    Obj4.Y2 := MMsToCoord(StrToFloat(List1[I1+5])) + Brd1.YOrigin;
  end;
  if Obj4 <> nil then
  begin
    if Obj5 <> nil then Obj4.Net := Obj5;
    Brd1.AddPCBObject(Obj4);
    PCBServer.SendMessageToRobots(Brd1.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj4.I_ObjectAddress);
    if B1 = 2 then begin Obj4.Selected := True; B1 := 0; end;
    I3 := I3 + 1;
  end;
  I1 := I1 + 8;
end;
List1.Clear;
SandboxLog('created ' + IntToStr(I3));
//## DELETE
List1.Sorted := False;
List1.LoadFromFile('{DEL}');
List1.Sorted := True;
OList1.Clear;
Obj1 := Brd1.BoardIterator_Create;
Obj1.AddFilter_ObjectSet(MkSet(eTrackObject, eArcObject, eViaObject));
Obj1.AddFilter_LayerSet(MkSet(eTopLayer, eBottomLayer, eMultiLayer));
Obj1.AddFilter_Method(eProcessAll);
Obj2 := Obj1.FirstPCBObject;
while Obj2 <> nil do
begin
  if Obj2.ObjectId = eTrackObject then
    S1 := 'T,' + IntToStr(Round(CoordToMMs(Obj2.x1 - Brd1.XOrigin)*1000)) + ',' + IntToStr(Round(CoordToMMs(Obj2.y1 - Brd1.YOrigin)*1000)) + ',' + IntToStr(Round(CoordToMMs(Obj2.x2 - Brd1.XOrigin)*1000)) + ',' + IntToStr(Round(CoordToMMs(Obj2.y2 - Brd1.YOrigin)*1000))
  else if Obj2.ObjectId = eArcObject then
    S1 := 'A,' + IntToStr(Round(CoordToMMs(Obj2.XCenter - Brd1.XOrigin)*1000)) + ',' + IntToStr(Round(CoordToMMs(Obj2.YCenter - Brd1.YOrigin)*1000)) + ',' + IntToStr(Round(CoordToMMs(Obj2.Radius)*1000))
  else
    S1 := 'V,' + IntToStr(Round(CoordToMMs(Obj2.x - Brd1.XOrigin)*1000)) + ',' + IntToStr(Round(CoordToMMs(Obj2.y - Brd1.YOrigin)*1000));
  if List1.IndexOf(S1) >= 0 then OList1.Add(Obj2);
  Obj2 := Obj1.NextPCBObject;
end;
Brd1.BoardIterator_Destroy(Obj1);
List1.Sorted := False;
List1.Clear;
if OList1.Count > {MAXDEL} then SandboxLog('TOO MANY TO DELETE ' + IntToStr(OList1.Count) + ' - nothing removed')
else
  for I1 := 0 to OList1.Count - 1 do
  begin
    Obj3 := OList1.Items[I1];
    Brd1.RemovePCBObject(Obj3);
    I2 := I2 + 1;
  end;
OList1.Clear;
SandboxLog('removed ' + IntToStr(I2));
//## TAIL
PCBServer.PostProcess;
Brd1.ViewManager_FullUpdate;
ResultText := 'created ' + IntToStr(I3) + ' / removed ' + IntToStr(I2) + ' | ' + ExtractFileName(Brd1.FileName);
end;
