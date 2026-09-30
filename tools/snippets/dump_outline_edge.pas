// stitch_vias.py 입력 덤프. run_altium_script 에 그대로 넣는다 (timeout_seconds: 45).
// {OUT} 을 저장 경로로, {BAND} 를 외곽에서 조회할 폭(mm, 예: 3)으로 바꾼다.
//
// 출력 한 줄 형식 (좌표는 보드 origin 기준 mm):
//   O|L|x|y                         외곽 꼭짓점 (직선 시작점)
//   O|A|x|y|cx|cy|r|a1|a2           외곽 아크 (시작점, 중심, 반지름, 시작·끝 각도)
//   T|layer|net|keepout|x1|y1|x2|y2|w          트랙
//   A|layer|net|keepout|cx|cy|r|a1|a2|w        아크
//   V|layer|net|keepout|x|y|size               비아
//   R|layer|net|keepout|x1|y1|x2|y2            패드·필·리전 (외접 사각형)
Brd1 := PCBServer.GetCurrentPCBBoard;
Obj1 := Brd1.BoardOutline;
for I1 := 0 to Obj1.PointCount - 1 do
begin
  S1 := FloatToStr(CoordToMMs(Obj1.Segments[I1].vx - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj1.Segments[I1].vy - Brd1.YOrigin));
  if Obj1.Segments[I1].Kind = ePolySegmentArc then
    List1.Add('O|A|' + S1 + '|' + FloatToStr(CoordToMMs(Obj1.Segments[I1].cx - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj1.Segments[I1].cy - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj1.Segments[I1].Radius)) + '|' + FloatToStr(Obj1.Segments[I1].Angle1) + '|' + FloatToStr(Obj1.Segments[I1].Angle2))
  else
    List1.Add('O|L|' + S1);
end;
I3 := MMsToCoord({BAND});
Obj1 := Brd1.BoardIterator_Create;
Obj1.AddFilter_ObjectSet(MkSet(ePadObject, eViaObject, eTrackObject, eArcObject, eFillObject, eRegionObject));
Obj1.AddFilter_LayerSet(AllLayers);
Obj1.AddFilter_Method(eProcessAll);
Obj2 := Obj1.FirstPCBObject;
while Obj2 <> nil do
begin
  // 외곽 폭 안에 걸친 객체만. 보드 전체를 덮는 폴리곤 조각은 GND 여도 경계를 넘으므로 여기 들어오지만,
  // InPolygon 이면 건너뛴다 (스티칭 비아가 올라가도 되는 대상).
  if (not Obj2.InPolygon) and ((Obj2.BoundingRectangle.Left - Brd1.BoardOutline.BoundingRectangle.Left < I3) or (Obj2.BoundingRectangle.Bottom - Brd1.BoardOutline.BoundingRectangle.Bottom < I3)
     or (Brd1.BoardOutline.BoundingRectangle.Right - Obj2.BoundingRectangle.Right < I3) or (Brd1.BoardOutline.BoundingRectangle.Top - Obj2.BoundingRectangle.Top < I3)) then
  begin
    S1 := '';
    if Obj2.InNet then S1 := Obj2.Net.Name;
    S2 := Layer2String(Obj2.Layer) + '|' + S1 + '|' + BoolToStr(Obj2.IsKeepout) + '|';
    if Obj2.ObjectId = eTrackObject then
      List1.Add('T|' + S2 + FloatToStr(CoordToMMs(Obj2.x1 - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y1 - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.x2 - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y2 - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.Width)))
    else if Obj2.ObjectId = eArcObject then
      List1.Add('A|' + S2 + FloatToStr(CoordToMMs(Obj2.XCenter - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.YCenter - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.Radius)) + '|' + FloatToStr(Obj2.StartAngle) + '|' + FloatToStr(Obj2.EndAngle) + '|' + FloatToStr(CoordToMMs(Obj2.LineWidth)))
    else if Obj2.ObjectId = eViaObject then
      List1.Add('V|' + S2 + FloatToStr(CoordToMMs(Obj2.x - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.Size)))
    else
      List1.Add('R|' + S2 + FloatToStr(CoordToMMs(Obj2.BoundingRectangle.Left - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangle.Bottom - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangle.Right - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangle.Top - Brd1.YOrigin)));
  end;
  Obj2 := Obj1.NextPCBObject;
end;
Brd1.BoardIterator_Destroy(Obj1);
List1.SaveToFile('{OUT}');
ResultText := IntToStr(List1.Count);
