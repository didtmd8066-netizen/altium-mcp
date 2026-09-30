// 보드 외곽(Board Shape)을 꼭짓점 목록으로 교체한다. run_altium_script (timeout_seconds: 45).
// {IN} 을 dxf_import.py 가 만든 shape.txt 경로로 바꾼다 (x, y 한 줄씩, 보드 origin 기준 mm).
//
// 여기까지만 한다 - 2026-09-30 검증:
//   Segments 를 넣은 뒤 EndModify / Invalidate / Rebuild / Validate / AreaSize 중 하나에서
//   디버거 일시정지가 났다. 외곽은 그 전에 이미 적용돼 있었고 FullUpdate 만으로 충분했다.
// 주의: AD24 는 Board Planning Mode 의 레이어 스택 영역(BoardRegions)을 따로 갖고 있어서
//   이 스크립트로는 바뀌지 않는다 -> 예전 모양이 점선으로 남는다. 외곽선을 선택하고
//   Design -> Board Shape -> Define Board Shape from Selected Objects 를 사용자가 한 번 해야 한다.
Brd1 := PCBServer.GetCurrentPCBBoard;
List1.LoadFromFile('{IN}');
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
ResultText := IntToStr(Obj1.PointCount);
