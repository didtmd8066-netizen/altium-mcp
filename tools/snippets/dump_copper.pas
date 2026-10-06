// 보드를 한 번에 덤프한다: 외곽, 부품, 동박 객체(비아·트랙·아크·패드, 선택 여부 포함).
// route_lib.load_board / load_dump, dxf_import.py --place-dump / --place-ref 의 입력.
// 직접 붙여 넣지 말고 `tools/plan_script.py dump` (또는 MCP 도구 dump_copper) 로 조립해서 쓴다 -
// {BOARD} 와 {OUT} 을 그쪽에서 채운다.
// 적용 직전에 다시 뜬다 - 사용자가 보드를 만진 뒤의 덤프로 계획을 세우면 부분 적용된다.
// 저장된 파일이면 Altium 없이 `tools/pcbdoc_dump.py` 로도 같은 형식을 얻는다 (선택 여부는 없다).
//
// 폴리곤이 부은 선·아크와 풋프린트에 속한 선·아크는 내지 않는다 (pcbdoc_dump.py 와 같은 기준).
//
// 한 줄 형식 (좌표는 보드 origin 기준 mm, 선택 여부는 -1 / 0):
//   O|L|x|y                          외곽 꼭짓점
//   O|A|x|y|cx|cy|반지름|시작각|끝각   외곽 아크
//   C|지정자|선택|x|y|회전|풋프린트
//   V|넷|선택|x|y|size
//   T|넷|선택|층|x1|y1|x2|y2|폭
//   A|넷|선택|층|cx|cy|반지름|시작각|끝각|폭
//   P|넷|선택|부품-핀|x|y|부품 회전|패드 x 크기|패드 y 크기|패드 회전(절대각)|층
//   R|넷|선택|층|x1|y1|x2|y2|종류       폴리곤이 부은 것이 아닌 리전·필의 외접 사각형 (copper / padshape = 풋프린트 소속 구리 / cutout / keepout)
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
  List1.Add('C|' + Obj2.Name.Text + '|' + BoolToStr(Obj2.Selected) + '|' + FloatToStr(CoordToMMs(Obj2.x - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y - Brd1.YOrigin)) + '|' + FloatToStr(Obj2.Rotation) + '|' + Obj2.Pattern);
  Obj2 := Obj1.NextPCBObject;
end;
Brd1.BoardIterator_Destroy(Obj1);
Obj1 := Brd1.BoardIterator_Create;
Obj1.AddFilter_ObjectSet(MkSet(eViaObject, eTrackObject, ePadObject, eArcObject));
Obj1.AddFilter_LayerSet(MkSet(eTopLayer, eBottomLayer, eMultiLayer));
Obj1.AddFilter_Method(eProcessAll);
Obj2 := Obj1.FirstPCBObject;
while Obj2 <> nil do
begin
  S1 := '';
  if Obj2.InNet then S1 := Obj2.Net.Name;
  S3 := BoolToStr(Obj2.Selected);
  // 폴리곤이 부은 선·아크(해치, 넷 없이 수천 개)와 풋프린트에 속한 선·아크는 배선이 아니다 - 뺀다.
  // 넣으면 간격 검사가 전부 오류로 뜨고 대칭 대조가 "대상에만" 으로 뒤덮인다.
  if ((Obj2.ObjectId = eTrackObject) or (Obj2.ObjectId = eArcObject)) and (Obj2.InPolygon or Obj2.InComponent) then S3 := 'skip';
  if S3 = 'skip' then S3 := ''
  else if Obj2.ObjectId = eViaObject then
    List1.Add('V|' + S1 + '|' + S3 + '|' + FloatToStr(CoordToMMs(Obj2.x - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.Size)))
  else if Obj2.ObjectId = eTrackObject then
    List1.Add('T|' + S1 + '|' + S3 + '|' + Layer2String(Obj2.Layer) + '|' + FloatToStr(CoordToMMs(Obj2.x1 - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y1 - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.x2 - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y2 - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.Width)))
  else if Obj2.ObjectId = ePadObject then
  begin
    // 부품에 속하지 않은 패드(가이드 홀 등)는 Component 가 nil 이다 - 그대로 읽으면 스크립트가 멈춘다
    S2 := '-' + Obj2.Name + '|' + FloatToStr(CoordToMMs(Obj2.x - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y - Brd1.YOrigin)) + '|';
    if Obj2.Component <> nil then S2 := Obj2.Component.Name.Text + S2 + FloatToStr(Obj2.Component.Rotation)
    else S2 := S2 + '0';
    List1.Add('P|' + S1 + '|' + S3 + '|' + S2 + '|' + FloatToStr(CoordToMMs(Obj2.TopXSize)) + '|' + FloatToStr(CoordToMMs(Obj2.TopYSize)) + '|' + FloatToStr(Obj2.Rotation) + '|' + Layer2String(Obj2.Layer));
  end
  else
    List1.Add('A|' + S1 + '|' + S3 + '|' + Layer2String(Obj2.Layer) + '|' + FloatToStr(CoordToMMs(Obj2.XCenter - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.YCenter - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.Radius)) + '|' + FloatToStr(Obj2.StartAngle) + '|' + FloatToStr(Obj2.EndAngle) + '|' + FloatToStr(CoordToMMs(Obj2.LineWidth)));
  Obj2 := Obj1.NextPCBObject;
end;
Brd1.BoardIterator_Destroy(Obj1);
Obj1 := Brd1.BoardIterator_Create;
Obj1.AddFilter_ObjectSet(MkSet(eRegionObject, eFillObject));
Obj1.AddFilter_LayerSet(MkSet(eTopLayer, eBottomLayer, eMultiLayer));
Obj1.AddFilter_Method(eProcessAll);
Obj2 := Obj1.FirstPCBObject;
while Obj2 <> nil do
begin
  if not Obj2.InPolygon then
  begin
    S1 := '';
    if Obj2.InNet then S1 := Obj2.Net.Name;
    S3 := 'copper';
    if Obj2.InComponent then S3 := 'padshape';
    if Obj2.ObjectId = eRegionObject then
      if Obj2.Kind = eRegionKind_Cutout then S3 := 'cutout';
    if Obj2.IsKeepout then S3 := 'keepout';
    List1.Add('R|' + S1 + '|' + BoolToStr(Obj2.Selected) + '|' + Layer2String(Obj2.Layer) + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangle.Left - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangle.Bottom - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangle.Right - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.BoundingRectangle.Top - Brd1.YOrigin)) + '|' + S3);
  end;
  Obj2 := Obj1.NextPCBObject;
end;
Brd1.BoardIterator_Destroy(Obj1);
List1.SaveToFile('{OUT}');
ResultText := IntToStr(List1.Count) + ' | ' + ExtractFileName(Brd1.FileName);
end;
