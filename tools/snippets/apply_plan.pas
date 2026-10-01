// route_lib.py 가 만든 계획을 보드에 적용한다: 기존 객체 삭제 -> 새 객체 생성. Undo 1회로 묶인다.
// run_altium_script 에 넣는다 (timeout_seconds: 45). {DEL}, {NEW} 를 파일 경로로, {MAXDEL} 을 삭제 예상 개수+몇 개로 바꾼다.
//
// {DEL}: 한 줄에 키 하나 (um 정수). route_lib.write_plan 이 반올림 경계값은 양쪽 다 넣어 준다.
//   T,x1,y1,x2,y2   A,cx,cy,r   V,x,y
// {NEW}: 한 객체당 8줄, 넷 이름 순 (넷 조회를 넷 종류 수만큼으로 줄이려고)
//   넷 / T / x1 / y1 / x2 / y2 / 층 / 폭
//   넷 / A / cx / cy / 반지름 / 시작각 / 끝각 / 층:폭
//   넷 / V / x / y / 견본x_um / 견본y_um / - / -
//
// 비아는 견본 비아(좌표로 지정)를 Replicate 해서 만든다. 텐팅은 스크립트로 못 켜므로
// 사용자가 쓰던 비아를 복제해야 텐팅·크기가 따라온다. 비아를 "옮길" 때는 옮길 비아를
// 견본으로 삼고 그 키를 {DEL} 에 넣는다 - 생성이 삭제보다 먼저라 견본이 살아 있다.
// 넷은 생성 시점에 넣는다 (기존 객체에 Obj.Net := 는 반영되지 않는다).
Brd1 := PCBServer.GetCurrentPCBBoard;
PCBServer.PreProcess;
List1.LoadFromFile('{NEW}');
S3 := '';
Obj5 := nil;
I1 := 0;
I3 := 0;
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
  if S1 = 'V' then
  begin
    Obj3 := nil;
    Obj1 := Brd1.BoardIterator_Create;
    Obj1.AddFilter_ObjectSet(MkSet(eViaObject));
    Obj1.AddFilter_LayerSet(AllLayers);
    Obj1.AddFilter_Method(eProcessAll);
    Obj2 := Obj1.FirstPCBObject;
    while Obj2 <> nil do
    begin
      if (Abs(Round(CoordToMMs(Obj2.x - Brd1.XOrigin)*1000) - StrToInt(List1[I1+4])) <= 2) and (Abs(Round(CoordToMMs(Obj2.y - Brd1.YOrigin)*1000) - StrToInt(List1[I1+5])) <= 2) then begin Obj3 := Obj2; Obj2 := nil; end
      else Obj2 := Obj1.NextPCBObject;
    end;
    Brd1.BoardIterator_Destroy(Obj1);
    if Obj3 = nil then SandboxLog('NO VIA TEMPLATE ' + List1[I1+4] + ',' + List1[I1+5])
    else
    begin
      Obj4 := Obj3.Replicate;
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
    I3 := I3 + 1;
  end;
  I1 := I1 + 8;
end;
SandboxLog('created ' + IntToStr(I3));
// 삭제: 순회 중에는 지우지 않는다. 하나 찾고 iterator 를 닫은 뒤 지우기를 반복한다.
// 방금 만든 객체가 지워지지 않도록 키는 "옛 좌표"만 들어 있어야 한다 (route_lib 가 겹침을 검사한다).
List1.LoadFromFile('{DEL}');
I2 := 0;
B1 := 1;
while B1 = 1 do
begin
  B1 := 0;
  Obj3 := nil;
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
    if List1.IndexOf(S1) >= 0 then begin Obj3 := Obj2; Obj2 := nil; end
    else Obj2 := Obj1.NextPCBObject;
  end;
  Brd1.BoardIterator_Destroy(Obj1);
  if Obj3 <> nil then begin Brd1.RemovePCBObject(Obj3); I2 := I2 + 1; B1 := 1; end;
  if I2 >= {MAXDEL} then B1 := 0;
end;
PCBServer.PostProcess;
Brd1.ViewManager_FullUpdate;
ResultText := 'created ' + IntToStr(I3) + ' / removed ' + IntToStr(I2);
