// 회로도 부품의 Description 을 계획대로 바꾸고(APPLY), 다시 읽어 낸다(READ).
// 직접 붙여 넣지 말고 `tools/plan_script.py descriptions` (또는 MCP 도구 apply_sch_descriptions) 로 조립한다.
//
// {PLAN}: `#<SchDoc 전체 경로>` 한 줄 뒤에 그 시트의 `지정자=새 Description` 줄들 (tools/sch_description.py 가 쓴다)
// - 열려 있지 않은 시트는 건너뛰고 'notopen: 경로' 를 남긴다.
// - 이미 같은 값이면 쓰지 않는다 (문서가 수정 표시되지 않게). 그 수는 S4 의 길이로 센다 - 정수 변수가 모자란다.
// - 한 시트 안에서 같은 지정자를 가진 부품(멀티파트)은 전부 바꾼다.
// - 시트마다 PreProcess / PostProcess 로 묶어 Undo 가 시트당 1회다. 바꿀 것이 없는 시트는 묶지도 않는다
//   (Obj4 가 깃발) - 방금 저장한 문서를 빈 Undo 로 다시 수정 표시하지 않기 위해서다. 저장은 하지 않는다.
// READ 는 반드시 별도 호출로 돌린다 - 같은 실행 안에서 읽으면 반영 안 된 값도 바뀐 것처럼 보일 수 있다.
//## APPLY
List1.LoadFromFile('{PLAN}');
I1 := 0;
B1 := 0;
S4 := '';
while I1 < List1.Count do
begin
  S1 := List1[I1];
  I2 := I1 + 1;
  while (I2 < List1.Count) and (Copy(List1[I2], 1, 1) <> '#') do I2 := I2 + 1;
  Obj1 := nil;
  if Copy(S1, 1, 1) = '#' then Obj1 := SchServer.GetSchDocumentByPath(Copy(S1, 2, 999));
  if Obj1 = nil then SandboxLog('notopen: ' + ExtractFileName(Copy(S1, 2, 999)))
  else
  begin
    Obj4 := '';
    Obj2 := Obj1.SchIterator_Create;
    Obj2.AddFilter_ObjectSet(MkSet(eSchComponent));
    Obj3 := Obj2.FirstSchObject;
    while Obj3 <> nil do
    begin
      S2 := Obj3.Designator.Text + '=';
      I3 := I1 + 1;
      while I3 < I2 do
      begin
        if Copy(List1[I3], 1, Length(S2)) = S2 then
        begin
          S3 := Copy(List1[I3], Length(S2) + 1, 999);
          if Obj3.ComponentDescription = S3 then S4 := S4 + '.'
          else
          begin
            if Obj4 = '' then
            begin
              SchServer.ProcessControl.PreProcess(Obj1, '');
              Obj4 := '1';
            end;
            SchServer.RobotManager.SendMessage(Obj3.I_ObjectAddress, c_BroadCast, SCHM_BeginModify, c_NoEventData);
            Obj3.ComponentDescription := S3;
            SchServer.RobotManager.SendMessage(Obj3.I_ObjectAddress, c_BroadCast, SCHM_EndModify, c_NoEventData);
            B1 := B1 + 1;
          end;
          I3 := I2;
        end;
        I3 := I3 + 1;
      end;
      Obj3 := Obj2.NextSchObject;
    end;
    Obj1.SchIterator_Destroy(Obj2);
    if Obj4 = '1' then
    begin
      SchServer.ProcessControl.PostProcess(Obj1, '');
      Obj1.GraphicallyInvalidate;
    end;
  end;
  I1 := I2;
end;
ResultText := 'set ' + IntToStr(B1) + ' / same ' + IntToStr(Length(S4));
//## READ
List1.LoadFromFile('{PLAN}');
I1 := 0;
B1 := 0;
I3 := List1.Count;
while I1 < I3 do
begin
  S1 := List1[I1];
  if Copy(S1, 1, 1) = '#' then
  begin
    Obj1 := SchServer.GetSchDocumentByPath(Copy(S1, 2, 999));
    if Obj1 <> nil then
    begin
      List1.Add('@' + Copy(S1, 2, 999));
      Obj2 := Obj1.SchIterator_Create;
      Obj2.AddFilter_ObjectSet(MkSet(eSchComponent));
      Obj3 := Obj2.FirstSchObject;
      while Obj3 <> nil do
      begin
        List1.Add(Obj3.Designator.Text + '=' + Obj3.ComponentDescription);
        B1 := B1 + 1;
        Obj3 := Obj2.NextSchObject;
      end;
      Obj1.SchIterator_Destroy(Obj2);
    end;
  end;
  I1 := I1 + 1;
end;
List1.SaveToFile('{OUT}');
ResultText := 'read ' + IntToStr(B1);
