// 넷을 넣은 채로 비아·트랙을 새로 만든다. run_altium_script 에 넣는다 (timeout_seconds: 45).
// {IN} 을 입력 파일 경로로 바꾼다. 한 번의 실행이 Undo 1회로 묶인다.
//
// 입력: 한 객체당 7줄, 넷 이름 순으로 정렬 (넷 조회를 넷 종류 수만큼으로 줄이려고).
//   비아: V / 넷 / x / y / size / hole / -
//   트랙: T / 넷 / x1 / y1 / x2 / y2 / 층:폭   (예: Bottom Layer:0.2, 층은 Layer2String 표기)
//   아크: A / 넷 / cx / cy / r / 시작각:끝각 / 층:폭   (원은 0:360)
// 넷이 없는 기구층 선은 넷 자리에 '-' 를 쓴다. 좌표·크기는 보드 origin 기준 mm.
// 비아는 Top-Bottom 관통으로 만든다.
//
// 비아 견본: 실행 전에 비아 하나를 선택해 두면 그 비아를 Replicate 로 복제해서 쓴다.
//   사용자가 쓰던 비아의 속성(텐팅, 크기, 솔더마스크 설정)이 그대로 따라온다. 이때 목록의
//   size/hole 은 무시한다. 텐팅은 스크립트로 켤 수 없으므로(IsTenting 쓰기 무시됨)
//   텐팅이 필요한 비아는 반드시 이 방식으로 만든다. 선택된 비아가 없으면 기본값으로 만든다.
//
// 주의: 이미 있는 객체에 Obj.Net := 는 반영되지 않는다. 넷은 반드시 생성 시점에 넣는다.
Brd1 := PCBServer.GetCurrentPCBBoard;
List1.LoadFromFile('{IN}');
Obj3 := nil;
Obj1 := Brd1.BoardIterator_Create;
Obj1.AddFilter_ObjectSet(MkSet(eViaObject));
Obj1.AddFilter_LayerSet(AllLayers);
Obj1.AddFilter_Method(eProcessAll);
Obj2 := Obj1.FirstPCBObject;
while Obj2 <> nil do
begin
  if Obj2.Selected then begin Obj3 := Obj2; Obj2 := nil; end
  else Obj2 := Obj1.NextPCBObject;
end;
Brd1.BoardIterator_Destroy(Obj1);
if Obj3 <> nil then SandboxLog('via template: selected via') else SandboxLog('via template: none (defaults)');
PCBServer.PreProcess;
S3 := '';
Obj5 := nil;
I1 := 0;
I3 := 0;
while I1 + 6 < List1.Count do
begin
  S1 := List1[I1];
  S2 := List1[I1+1];
  if (S2 <> S3) and (S2 = '-') then begin Obj5 := nil; S3 := S2; end;
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
    if Obj5 = nil then SandboxLog('NO NET ' + S2);
  end;
  if S1 = 'V' then
  begin
    if Obj3 <> nil then
      Obj4 := Obj3.Replicate
    else
    begin
      Obj4 := PCBServer.PCBObjectFactory(eViaObject, eNoDimension, eCreate_Default);
      Obj4.Size := MMsToCoord(StrToFloat(List1[I1+4]));
      Obj4.HoleSize := MMsToCoord(StrToFloat(List1[I1+5]));
      Obj4.LowLayer := eTopLayer;
      Obj4.HighLayer := eBottomLayer;
    end;
    Obj4.Selected := False;
    Obj4.x := MMsToCoord(StrToFloat(List1[I1+2])) + Brd1.XOrigin;
    Obj4.y := MMsToCoord(StrToFloat(List1[I1+3])) + Brd1.YOrigin;
  end
  else if S1 = 'A' then
  begin
    Obj4 := PCBServer.PCBObjectFactory(eArcObject, eNoDimension, eCreate_Default);
    Obj4.XCenter := MMsToCoord(StrToFloat(List1[I1+2])) + Brd1.XOrigin;
    Obj4.YCenter := MMsToCoord(StrToFloat(List1[I1+3])) + Brd1.YOrigin;
    Obj4.Radius := MMsToCoord(StrToFloat(List1[I1+4]));
    S1 := List1[I1+5];
    B1 := Pos(':', S1);
    Obj4.StartAngle := StrToFloat(Copy(S1, 1, B1 - 1));
    Obj4.EndAngle := StrToFloat(Copy(S1, B1 + 1, 20));
    S1 := List1[I1+6];
    B1 := Pos(':', S1);
    Obj4.Layer := String2Layer(Copy(S1, 1, B1 - 1));
    Obj4.LineWidth := MMsToCoord(StrToFloat(Copy(S1, B1 + 1, 20)));
  end
  else
  begin
    S1 := List1[I1+6];
    B1 := Pos(':', S1);
    Obj4 := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
    Obj4.Layer := String2Layer(Copy(S1, 1, B1 - 1));
    Obj4.Width := MMsToCoord(StrToFloat(Copy(S1, B1 + 1, 20)));
    Obj4.X1 := MMsToCoord(StrToFloat(List1[I1+2])) + Brd1.XOrigin;
    Obj4.Y1 := MMsToCoord(StrToFloat(List1[I1+3])) + Brd1.YOrigin;
    Obj4.X2 := MMsToCoord(StrToFloat(List1[I1+4])) + Brd1.XOrigin;
    Obj4.Y2 := MMsToCoord(StrToFloat(List1[I1+5])) + Brd1.YOrigin;
  end;
  if Obj5 <> nil then Obj4.Net := Obj5;
  Brd1.AddPCBObject(Obj4);
  PCBServer.SendMessageToRobots(Brd1.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj4.I_ObjectAddress);
  I3 := I3 + 1;
  I1 := I1 + 7;
end;
PCBServer.PostProcess;
Brd1.ViewManager_FullUpdate;
ResultText := IntToStr(I3);
