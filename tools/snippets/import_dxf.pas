// dxf_import.py 결과를 한 번에 넣는다: objs.txt 의 선·원 생성 -> shape.txt 로 보드 외곽 교체.
// run_altium_script (timeout_seconds: 45). {OBJS}, {SHAPE} 를 파일 경로로 바꾼다.
// create_from_list.pas + set_board_shape.pas 를 따로 부르던 것을 합친 것 (2026-10-01 BOT_RIGHT 에서 검증:
// 433 개 생성 + 꼭짓점 137 개). 넷 없는 기구층 선·원만 다루므로 넷 조회와 비아 처리는 없다.
// 외곽 교체 뒤에는 FullUpdate 만 한다 - EndModify / Rebuild 계열은 디버거 일시정지를 낸다.
// 예전 모양이 점선으로 남으면 사용자가 Define Board Shape from Selected Objects 를 한 번 해야 한다.
Brd1 := PCBServer.GetCurrentPCBBoard;
List1.LoadFromFile('{OBJS}');
PCBServer.PreProcess;
I1 := 0;
I3 := 0;
while I1 + 6 < List1.Count do
begin
  S1 := List1[I1];
  if S1 = 'A' then
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
  Brd1.AddPCBObject(Obj4);
  PCBServer.SendMessageToRobots(Brd1.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj4.I_ObjectAddress);
  I3 := I3 + 1;
  I1 := I1 + 7;
end;
PCBServer.PostProcess;
SandboxLog('created ' + IntToStr(I3));
List1.LoadFromFile('{SHAPE}');
I2 := List1.Count div 2;
PCBServer.PreProcess;
Obj1 := Brd1.BoardOutline;
Obj1.BeginModify;
Obj1.PointCount := I2;
for I1 := 0 to I2 - 1 do
begin
  Obj3 := TPolySegment;
  Obj3.Kind := ePolySegmentLine;
  Obj3.vx := MMsToCoord(StrToFloat(List1[I1*2])) + Brd1.XOrigin;
  Obj3.vy := MMsToCoord(StrToFloat(List1[I1*2+1])) + Brd1.YOrigin;
  Obj1.Segments[I1] := Obj3;
end;
PCBServer.PostProcess;
Brd1.ViewManager_FullUpdate;
ResultText := 'created ' + IntToStr(I3) + ' / outline pts ' + IntToStr(Obj1.PointCount);
