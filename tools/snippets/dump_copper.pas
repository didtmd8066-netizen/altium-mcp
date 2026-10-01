// 보드의 동박 객체(비아·트랙·아크·패드)를 선택 여부와 함께 덤프한다. route_lib.py 의 입력.
// run_altium_script 에 넣는다 (timeout_seconds: 45). {OUT} 을 저장 경로로 바꾼다.
//
// 한 줄 형식 (좌표는 보드 origin 기준 mm, 선택 여부는 -1 / 0):
//   V|넷|선택|x|y|size
//   T|넷|선택|층|x1|y1|x2|y2|폭
//   A|넷|선택|층|cx|cy|반지름|시작각|끝각
//   P|넷|선택|부품-핀|x|y|부품 회전
Brd1 := PCBServer.GetCurrentPCBBoard;
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
  if Obj2.ObjectId = eViaObject then
    List1.Add('V|' + S1 + '|' + S3 + '|' + FloatToStr(CoordToMMs(Obj2.x - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.Size)))
  else if Obj2.ObjectId = eTrackObject then
    List1.Add('T|' + S1 + '|' + S3 + '|' + Layer2String(Obj2.Layer) + '|' + FloatToStr(CoordToMMs(Obj2.x1 - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y1 - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.x2 - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y2 - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.Width)))
  else if Obj2.ObjectId = ePadObject then
    List1.Add('P|' + S1 + '|' + S3 + '|' + Obj2.Component.Name.Text + '-' + Obj2.Name + '|' + FloatToStr(CoordToMMs(Obj2.x - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.y - Brd1.YOrigin)) + '|' + FloatToStr(Obj2.Component.Rotation))
  else
    List1.Add('A|' + S1 + '|' + S3 + '|' + Layer2String(Obj2.Layer) + '|' + FloatToStr(CoordToMMs(Obj2.XCenter - Brd1.XOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.YCenter - Brd1.YOrigin)) + '|' + FloatToStr(CoordToMMs(Obj2.Radius)) + '|' + FloatToStr(Obj2.StartAngle) + '|' + FloatToStr(Obj2.EndAngle));
  Obj2 := Obj1.NextPCBObject;
end;
Brd1.BoardIterator_Destroy(Obj1);
List1.SaveToFile('{OUT}');
ResultText := Brd1.FileName + ' | ' + IntToStr(List1.Count);
