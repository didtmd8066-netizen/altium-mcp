// 부품 배치용 덤프: 외곽과, 부품마다 위치·3D 바디 범위·패드 범위·전체 범위.
// 직접 붙여 넣지 말고 `tools/plan_script.py components` (또는 MCP 도구 dump_components) 로 조립한다.
// sheet_groups.py 의 입력.
//
// 한 줄 형식 (좌표는 보드 origin 기준 mm):
//   O|L|x|y  /  O|A|...                 외곽 (dump_copper.pas 와 같다)
//   K|지정자|선택|x|y|회전|층|풋프린트|바디 L|B|R|T|패드 L|B|R|T|전체 L|B|R|T
// 바디 = 부품에 속한 3D 바디(ComponentBody)들의 외접 사각형. 없으면 네 칸이 빈다.
// 패드 = 패드들의 외접 사각형. 전체 = 이름·코멘트를 뺀 부품 전체 (실크 포함).
// 지정자는 겹칠 수 있다 (annotate 안 된 R? Q?). 그래서 부품을 가릴 때는 좌표를 같이 쓴다.
{BOARD}
if Brd1 = nil then ResultText := 'NO BOARD'
else
begin
Obj1 := Brd1.BoardOutline;
for I1 := 0 to Obj1.PointCount - 1 do
begin
  S1 := FloatToStr(CoordToMMs(Obj1.Segments[I1].vx - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj1.Segments[I1].vy - Brd1.YOrigin));
  if Obj1.Segments[I1].Kind = ePolySegmentArc then
    List1.Add('O|A|' + S1 + '|' + FloatToStr(CoordToMMs(Obj1.Segments[I1].cx - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj1.Segments[I1].cy - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj1.Segments[I1].Radius)) + '|' + FloatToStr(Obj1.Segments[I1].Angle1) + '|' + FloatToStr(Obj1.Segments[I1].Angle2))
  else
    List1.Add('O|L|' + S1);
end;
Obj1 := Brd1.BoardIterator_Create;
Obj1.AddFilter_ObjectSet(MkSet(eComponentObject));
Obj1.AddFilter_LayerSet(AllLayers);
Obj1.AddFilter_Method(eProcessAll);
Obj2 := Obj1.FirstPCBObject;
while Obj2 <> nil do
begin
  S2 := '';
  Obj3 := Obj2.GroupIterator_Create;
  Obj3.SetState_FilterAll;
  Obj3.AddFilter_ObjectSet(MkSet(eComponentBodyObject));
  Obj4 := Obj3.FirstPCBObject;
  while Obj4 <> nil do
  begin
    if S2 = '' then
    begin
      I1 := Obj4.BoundingRectangle.Left; I2 := Obj4.BoundingRectangle.Bottom; I3 := Obj4.BoundingRectangle.Right; B1 := Obj4.BoundingRectangle.Top;
      S2 := 'B';
    end
    else
    begin
      if Obj4.BoundingRectangle.Left < I1 then I1 := Obj4.BoundingRectangle.Left;
      if Obj4.BoundingRectangle.Bottom < I2 then I2 := Obj4.BoundingRectangle.Bottom;
      if Obj4.BoundingRectangle.Right > I3 then I3 := Obj4.BoundingRectangle.Right;
      if Obj4.BoundingRectangle.Top > B1 then B1 := Obj4.BoundingRectangle.Top;
    end;
    Obj4 := Obj3.NextPCBObject;
  end;
  Obj2.GroupIterator_Destroy(Obj3);
  if S2 = '' then S3 := '|||'
  else S3 := FloatToStr(CoordToMMs(I1 - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(I2 - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(I3 - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(B1 - Brd1.YOrigin));
  S2 := '';
  Obj3 := Obj2.GroupIterator_Create;
  Obj3.SetState_FilterAll;
  Obj3.AddFilter_ObjectSet(MkSet(ePadObject));
  Obj4 := Obj3.FirstPCBObject;
  while Obj4 <> nil do
  begin
    if S2 = '' then
    begin
      I1 := Obj4.BoundingRectangle.Left; I2 := Obj4.BoundingRectangle.Bottom; I3 := Obj4.BoundingRectangle.Right; B1 := Obj4.BoundingRectangle.Top;
      S2 := 'P';
    end
    else
    begin
      if Obj4.BoundingRectangle.Left < I1 then I1 := Obj4.BoundingRectangle.Left;
      if Obj4.BoundingRectangle.Bottom < I2 then I2 := Obj4.BoundingRectangle.Bottom;
      if Obj4.BoundingRectangle.Right > I3 then I3 := Obj4.BoundingRectangle.Right;
      if Obj4.BoundingRectangle.Top > B1 then B1 := Obj4.BoundingRectangle.Top;
    end;
    Obj4 := Obj3.NextPCBObject;
  end;
  Obj2.GroupIterator_Destroy(Obj3);
  if S2 = '' then S1 := '|||'
  else S1 := FloatToStr(CoordToMMs(I1 - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(I2 - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(I3 - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(B1 - Brd1.YOrigin));
  List1.Add('K|' + Obj2.Name.Text + '|' + BoolToStr(Obj2.Selected) + '|' + FloatToStr(CoordToMMs(Obj2.x - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y - Brd1.YOrigin)) + '|' + FloatToStr(Obj2.Rotation) + '|' + Layer2String(Obj2.Layer) + '|' + Obj2.Pattern + '|' + S3 + '|' + S1 + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangleNoNameComment.Left - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangleNoNameComment.Bottom - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangleNoNameComment.Right - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangleNoNameComment.Top - Brd1.YOrigin)));
  Obj2 := Obj1.NextPCBObject;
end;
Brd1.BoardIterator_Destroy(Obj1);
List1.SaveToFile('{OUT}');
ResultText := IntToStr(List1.Count) + ' | ' + ExtractFileName(Brd1.FileName);
end;
