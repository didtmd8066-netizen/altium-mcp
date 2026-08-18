// Nil-safe access to the current PCB board. When no PCB document has ever
// been opened this session, PCBServer itself is nil and calling
// GetCurrentPCBBoard on it throws an access violation that leaves the
// script paused in the debugger - silently blocking every later script run.
// All board lookups must go through this helper.
function GetBoardSafe(Dummy: Integer): IPCB_Board;
begin
    Result := nil;
    if (PCBServer <> nil) then
        Result := PCBServer.GetCurrentPCBBoard;
end;

// Nil-safe access to the current PCB library (same hazard as GetBoardSafe)
function GetPcbLibSafe(Dummy: Integer): IPCB_Library;
begin
    Result := nil;
    if (PCBServer <> nil) then
        Result := PCBServer.GetCurrentPCBLibrary;
end;

// Create many footprints in a single script run from a spec file (plain
// text, pipe-delimited; coords in mils, layers as names, shapes/hole types
// as raw enum ints - symmetric with get_footprint_primitives):
//   FPLIB|<path to .PcbLib>              (optional first line - focus/open)
//   FOOTPRINT|<name>|<description>
//   PAD|name|x|y|rot|layer|plated|hole_size|hole_type|hole_width|hole_rot|top_x|top_y|top_shape[|corner_pct[|mode|mid_x|mid_y|mid_shape|bot_x|bot_y|bot_shape]]
//   TRACK|x1|y1|x2|y2|width|layer
//   ARC|cx|cy|radius|start_angle|end_angle|width|layer
//   FILL|x1|y1|x2|y2|rotation|layer
//   TEXT|x|y|size|width|rotation|layer|mirror|ttf|text
function CreateFootprintsBatch(SpecFilePath: String): String;
var
    PcbLib      : IPCB_Library;
    LibComp     : IPCB_LibComponent;
    ServerDoc   : IServerDocument;
    Lines       : TStringList;
    FailedArray : TStringList;
    ResultProps : TStringList;
    Pad         : IPCB_Pad;
    Track       : IPCB_Track;
    Arc         : IPCB_Arc;
    Fill        : IPCB_Fill;
    Text        : IPCB_Text;
    Region      : IPCB_Region;
    Contour     : IPCB_Contour;
    Via         : IPCB_Via;
    Line, Kind  : String;
    LibPath     : String;
    FieldValue  : String;
    CreatedCount: Integer;
    PrimErrors  : Integer;
    i, V        : Integer;


begin
    if not FileExists(SpecFilePath) then
    begin
        Result := 'ERROR: Spec file not found: ' + SpecFilePath;
        Exit;
    end;

    Lines := TStringList.Create;
    FailedArray := TStringList.Create;
    ResultProps := TStringList.Create;
    LibComp := nil;
    CreatedCount := 0;
    PrimErrors := 0;

    try
        Lines.LoadFromFile(SpecFilePath);

        for i := 0 to Lines.Count - 1 do
        begin
            Line := Lines[i];
            Kind := UpperCase(Trim(GetFieldFromPipeString(Line, 0)));

            try
                if (Kind = 'FPLIB') then
                begin
                    LibPath := GetFieldFromPipeString(Line, 1);
                    if (LibPath <> '') and FileExists(LibPath) then
                    begin
                        if Client.IsDocumentOpen(LibPath) then
                            ServerDoc := Client.GetDocumentByPath(LibPath)
                        else
                            ServerDoc := Client.OpenDocument('PcbLib', LibPath);
                        if (ServerDoc <> Nil) then
                        begin
                            Client.ShowDocument(ServerDoc);
                            Sleep(500);
                        end;
                    end;
                end
                else if (Kind = 'FOOTPRINT') then
                begin
                    PcbLib := GetPcbLibSafe(0);
                    // Focus can drift between chunks - retry via the opened
                    // document before giving up
                    if (PcbLib = nil) and (ServerDoc <> nil) then
                    begin
                        Client.ShowDocument(ServerDoc);
                        Sleep(1000);
                        PcbLib := GetPcbLibSafe(0);
                    end;
                    if (PcbLib = nil) then
                    begin
                        Result := 'ERROR: No PCB library document is active';
                        Exit;
                    end;
                    LibComp := PCBServer.CreatePCBLibComp;
                    LibComp.Name := Trim(GetFieldFromPipeString(Line, 1));
                    LibComp.Description := GetFieldFromPipeString(Line, 2);
                    PcbLib.RegisterComponent(LibComp);
                    CreatedCount := CreatedCount + 1;
                end
                else if (LibComp <> nil) and (Kind = 'PAD') then
                begin
                    Pad := PCBServer.PCBObjectFactory(ePadObject, eNoDimension, eCreate_Default);
                    // Pad name is NOT trimmed - round-trip fidelity preserves
                    // whitespace and even control characters found in source data
                    Pad.Name := GetFieldFromPipeString(Line, 1);
                    // Mode first so per-stack sizes land correctly
                    FieldValue := Trim(GetFieldFromPipeString(Line, 15));
                    if (FieldValue <> '') then
                        Pad.Mode := StrToInt(FieldValue)
                    else
                        Pad.Mode := ePadMode_Simple;
                    Pad.x := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 2))));
                    Pad.y := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 3))));
                    Pad.Layer := String2Layer(Trim(GetFieldFromPipeString(Line, 5)));
                    Pad.Plated := (Trim(GetFieldFromPipeString(Line, 6)) = '1');
                    Pad.HoleSize := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 7))));
                    Pad.HoleType := StrToInt(Trim(GetFieldFromPipeString(Line, 8)));
                    Pad.HoleWidth := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 9))));
                    Pad.HoleRotation := SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 10)));
                    Pad.TopXSize := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 11))));
                    Pad.TopYSize := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 12))));
                    Pad.TopShape := StrToInt(Trim(GetFieldFromPipeString(Line, 13)));
                    FieldValue := Trim(GetFieldFromPipeString(Line, 14));
                    if (FieldValue <> '') then
                        Pad.StackCRPctOnLayer[eTopLayer] := StrToInt(FieldValue);
                    if (Pad.Mode <> ePadMode_Simple) then
                    begin
                        Pad.MidXSize := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 16))));
                        Pad.MidYSize := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 17))));
                        Pad.MidShape := StrToInt(Trim(GetFieldFromPipeString(Line, 18)));
                        Pad.BotXSize := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 19))));
                        Pad.BotYSize := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 20))));
                        Pad.BotShape := StrToInt(Trim(GetFieldFromPipeString(Line, 21)));
                    end;
                    // Rotation last: it rotates the pad about its location
                    Pad.Rotation := SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 4)));
                    LibComp.AddPCBObject(Pad);
                    PCBServer.SendMessageToRobots(Pad.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);
                end
                else if (LibComp <> nil) and (Kind = 'TRACK') then
                begin
                    Track := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
                    Track.x1 := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 1))));
                    Track.y1 := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 2))));
                    Track.x2 := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 3))));
                    Track.y2 := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 4))));
                    Track.Width := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 5))));
                    Track.Layer := String2Layer(Trim(GetFieldFromPipeString(Line, 6)));
                    LibComp.AddPCBObject(Track);
                    PCBServer.SendMessageToRobots(Track.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);
                end
                else if (LibComp <> nil) and (Kind = 'ARC') then
                begin
                    Arc := PCBServer.PCBObjectFactory(eArcObject, eNoDimension, eCreate_Default);
                    Arc.XCenter := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 1))));
                    Arc.YCenter := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 2))));
                    Arc.Radius := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 3))));
                    Arc.StartAngle := SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 4)));
                    Arc.EndAngle := SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 5)));
                    Arc.LineWidth := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 6))));
                    Arc.Layer := String2Layer(Trim(GetFieldFromPipeString(Line, 7)));
                    LibComp.AddPCBObject(Arc);
                    PCBServer.SendMessageToRobots(Arc.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);
                end
                else if (LibComp <> nil) and (Kind = 'FILL') then
                begin
                    Fill := PCBServer.PCBObjectFactory(eFillObject, eNoDimension, eCreate_Default);
                    Fill.x1Location := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 1))));
                    Fill.y1Location := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 2))));
                    Fill.x2Location := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 3))));
                    Fill.y2Location := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 4))));
                    Fill.Rotation := SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 5)));
                    Fill.Layer := String2Layer(Trim(GetFieldFromPipeString(Line, 6)));
                    LibComp.AddPCBObject(Fill);
                    PCBServer.SendMessageToRobots(Fill.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);
                end
                else if (LibComp <> nil) and (Kind = 'VIA') then
                begin
                    Via := PCBServer.PCBObjectFactory(eViaObject, eNoDimension, eCreate_Default);
                    Via.x := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 1))));
                    Via.y := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 2))));
                    Via.Size := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 3))));
                    Via.HoleSize := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 4))));
                    Via.LowLayer := String2Layer(Trim(GetFieldFromPipeString(Line, 5)));
                    Via.HighLayer := String2Layer(Trim(GetFieldFromPipeString(Line, 6)));
                    LibComp.AddPCBObject(Via);
                    PCBServer.SendMessageToRobots(Via.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);
                end
                else if (LibComp <> nil) and (Kind = 'REGION') then
                begin
                    Region := PCBServer.PCBObjectFactory(eRegionObject, eNoDimension, eCreate_Default);
                    Contour := PCBServer.PCBContourFactory;
                    V := 3;
                    while (Trim(GetFieldFromPipeString(Line, V)) <> '') do
                    begin
                        Contour.AddPoint(MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, V)))),
                                         MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, V + 1)))));
                        V := V + 2;
                    end;
                    Region.SetOutlineContour(Contour);
                    Region.Layer := String2Layer(Trim(GetFieldFromPipeString(Line, 1)));
                    Region.Kind := StrToInt(Trim(GetFieldFromPipeString(Line, 2)));
                    LibComp.AddPCBObject(Region);
                    PCBServer.SendMessageToRobots(Region.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);
                end
                else if (LibComp <> nil) and (Kind = 'TEXT') then
                begin
                    Text := PCBServer.PCBObjectFactory(eTextObject, eNoDimension, eCreate_Default);
                    Text.XLocation := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 1))));
                    Text.YLocation := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 2))));
                    Text.Size := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 3))));
                    Text.Width := MilsToCoord(SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 4))));
                    Text.Layer := String2Layer(Trim(GetFieldFromPipeString(Line, 6)));
                    Text.MirrorFlag := (Trim(GetFieldFromPipeString(Line, 7)) = '1');
                    Text.UseTTFonts := (Trim(GetFieldFromPipeString(Line, 8)) = '1');
                    // <NL> placeholder carries embedded newlines through the
                    // line-based spec file
                    Text.Text := StringReplace(GetFieldFromPipeString(Line, 9), '<NL>', #13#10, REPLACEALL);
                    Text.Rotation := SafeStrToFloat(Trim(GetFieldFromPipeString(Line, 5)));
                    LibComp.AddPCBObject(Text);
                    PCBServer.SendMessageToRobots(Text.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);
                end;
            except
                PrimErrors := PrimErrors + 1;
                if (Kind = 'FOOTPRINT') then
                    FailedArray.Add('"' + JSONEscapeString(Trim(GetFieldFromPipeString(Line, 1))) + '"');
            end;
        end;

        AddJSONInteger(ResultProps, 'created', CreatedCount);
        AddJSONInteger(ResultProps, 'primitive_errors', PrimErrors);
        if (FailedArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(FailedArray, 'failed'))
        else
            ResultProps.Add('"failed": []');

        Result := BuildJSONObject(ResultProps);
    finally
        Lines.Free;
        FailedArray.Free;
        ResultProps.Free;
    end;
end;

// Get the graphic/copper primitives of footprints in a PCB library.
// FootprintName = '' -> inventory (per-footprint primitive counts);
// '*' -> full dump of every footprint; name -> dump that footprint.
// Coordinates in mils, layers as names, shapes/hole types as raw enum ints
// (pass-through symmetric with create_footprints_batch).
function GetFootprintPrimitives(ROOT_DIR: String; LibraryPath: String; FootprintName: String): String;
var
    PcbLib      : IPCB_Library;
    LibComp     : IPCB_LibComponent;
    GrpIter     : IPCB_GroupIterator;
    Prim        : IPCB_Primitive;
    ServerDoc   : IServerDocument;
    ResultProps : TStringList;
    FPArray     : TStringList;
    FPProps     : TStringList;
    PrimsArray  : TStringList;
    PrimProps   : TStringList;
    PointsArray : TStringList;
    PProps      : TStringList;
    Counts      : TStringList;
    OutputLines : TStringList;
    TypeName    : String;
    i, C, V     : Integer;
    Found       : Boolean;
begin
    Result := '';

    if (LibraryPath <> '') then
    begin
        if not FileExists(LibraryPath) then
        begin
            Result := 'ERROR: Library file not found: ' + LibraryPath;
            Exit;
        end;
        // Never re-open an open document (reload discards unsaved changes)
        if Client.IsDocumentOpen(LibraryPath) then
            ServerDoc := Client.GetDocumentByPath(LibraryPath)
        else
            ServerDoc := Client.OpenDocument('PcbLib', LibraryPath);
        if ServerDoc = Nil then
        begin
            Result := 'ERROR: Failed to open library: ' + LibraryPath;
            Exit;
        end;
        Client.ShowDocument(ServerDoc);
        Sleep(500);
    end;

    PcbLib := GetPcbLibSafe(0);
    if (PcbLib = nil) then
    begin
        Result := 'ERROR: No PCB library is open (provide library_path or open a .PcbLib)';
        Exit;
    end;

    ResultProps := TStringList.Create;
    FPArray := TStringList.Create;
    Found := False;

    try
        AddJSONProperty(ResultProps, 'library_name', ExtractFileName(PcbLib.Board.FileName));

        for C := 0 to PcbLib.ComponentCount - 1 do
        begin
            LibComp := PcbLib.GetComponent(C);

            if (FootprintName = '') then
            begin
                // Inventory mode
                Counts := TStringList.Create;
                FPProps := TStringList.Create;
                try
                    GrpIter := LibComp.GroupIterator_Create;
                    Prim := GrpIter.FirstPCBObject;
                    while (Prim <> nil) do
                    begin
                        case Prim.ObjectId of
                            ePadObject:           TypeName := 'pads';
                            eTrackObject:         TypeName := 'tracks';
                            eArcObject:           TypeName := 'arcs';
                            eFillObject:          TypeName := 'fills';
                            eTextObject:          TypeName := 'texts';
                            eRegionObject:        TypeName := 'regions';
                            eViaObject:           TypeName := 'vias';
                            eComponentBodyObject: TypeName := 'component_bodies';
                        else
                            TypeName := 'other';
                        end;
                        i := Counts.IndexOfName(TypeName);
                        if (i < 0) then
                            Counts.Add(TypeName + '=1')
                        else
                            Counts[i] := TypeName + '=' + IntToStr(StrToInt(Counts.ValueFromIndex[i]) + 1);
                        Prim := GrpIter.NextPCBObject;
                    end;
                    LibComp.GroupIterator_Destroy(GrpIter);

                    AddJSONProperty(FPProps, 'name', LibComp.Name);
                    AddJSONProperty(FPProps, 'description', LibComp.Description);
                    for i := 0 to Counts.Count - 1 do
                        AddJSONInteger(FPProps, Counts.Names[i], StrToInt(Counts.ValueFromIndex[i]));
                    FPArray.Add(BuildJSONObject(FPProps, 1));
                finally
                    Counts.Free;
                    FPProps.Free;
                end;
            end
            else if (FootprintName = '*') or (UpperCase(LibComp.Name) = UpperCase(FootprintName)) then
            begin
                // Dump mode
                Found := True;
                FPProps := TStringList.Create;
                PrimsArray := TStringList.Create;
                try
                    AddJSONProperty(FPProps, 'footprint_name', LibComp.Name);
                    AddJSONProperty(FPProps, 'description', LibComp.Description);

                    GrpIter := LibComp.GroupIterator_Create;
                    Prim := GrpIter.FirstPCBObject;
                    while (Prim <> nil) do
                    begin
                        PrimProps := TStringList.Create;
                        try
                          // Armor: an unreadable primitive degrades to a
                          // reported entry instead of crashing the script
                          try
                            case Prim.ObjectId of
                                ePadObject:
                                begin
                                    AddJSONProperty(PrimProps, 'type', 'pad');
                                    AddJSONProperty(PrimProps, 'name', Prim.Name);
                                    AddJSONNumber(PrimProps, 'x', CoordToMils(Prim.x));
                                    AddJSONNumber(PrimProps, 'y', CoordToMils(Prim.y));
                                    AddJSONNumber(PrimProps, 'rotation', Prim.Rotation);
                                    AddJSONProperty(PrimProps, 'layer', Layer2String(Prim.Layer));
                                    AddJSONBoolean(PrimProps, 'plated', Prim.Plated);
                                    AddJSONInteger(PrimProps, 'mode', Prim.Mode);
                                    AddJSONNumber(PrimProps, 'top_x_size', CoordToMils(Prim.TopXSize));
                                    AddJSONNumber(PrimProps, 'top_y_size', CoordToMils(Prim.TopYSize));
                                    AddJSONInteger(PrimProps, 'top_shape', Prim.TopShape);
                                    AddJSONNumber(PrimProps, 'hole_size', CoordToMils(Prim.HoleSize));
                                    AddJSONInteger(PrimProps, 'hole_type', Prim.HoleType);
                                    AddJSONNumber(PrimProps, 'hole_width', CoordToMils(Prim.HoleWidth));
                                    AddJSONNumber(PrimProps, 'hole_rotation', Prim.HoleRotation);
                                    if (Prim.Mode <> ePadMode_Simple) then
                                    begin
                                        AddJSONNumber(PrimProps, 'mid_x_size', CoordToMils(Prim.MidXSize));
                                        AddJSONNumber(PrimProps, 'mid_y_size', CoordToMils(Prim.MidYSize));
                                        AddJSONInteger(PrimProps, 'mid_shape', Prim.MidShape);
                                        AddJSONNumber(PrimProps, 'bot_x_size', CoordToMils(Prim.BotXSize));
                                        AddJSONNumber(PrimProps, 'bot_y_size', CoordToMils(Prim.BotYSize));
                                        AddJSONInteger(PrimProps, 'bot_shape', Prim.BotShape);
                                    end;
                                    if (Prim.TopShape = eRoundedRectangular) then
                                        AddJSONInteger(PrimProps, 'corner_pct', Prim.StackCRPctOnLayer[eTopLayer]);
                                end;
                                eTrackObject:
                                begin
                                    AddJSONProperty(PrimProps, 'type', 'track');
                                    AddJSONNumber(PrimProps, 'x1', CoordToMils(Prim.x1));
                                    AddJSONNumber(PrimProps, 'y1', CoordToMils(Prim.y1));
                                    AddJSONNumber(PrimProps, 'x2', CoordToMils(Prim.x2));
                                    AddJSONNumber(PrimProps, 'y2', CoordToMils(Prim.y2));
                                    AddJSONNumber(PrimProps, 'width', CoordToMils(Prim.Width));
                                    AddJSONProperty(PrimProps, 'layer', Layer2String(Prim.Layer));
                                end;
                                eArcObject:
                                begin
                                    AddJSONProperty(PrimProps, 'type', 'arc');
                                    AddJSONNumber(PrimProps, 'cx', CoordToMils(Prim.XCenter));
                                    AddJSONNumber(PrimProps, 'cy', CoordToMils(Prim.YCenter));
                                    AddJSONNumber(PrimProps, 'radius', CoordToMils(Prim.Radius));
                                    AddJSONNumber(PrimProps, 'start_angle', Prim.StartAngle);
                                    AddJSONNumber(PrimProps, 'end_angle', Prim.EndAngle);
                                    AddJSONNumber(PrimProps, 'width', CoordToMils(Prim.LineWidth));
                                    AddJSONProperty(PrimProps, 'layer', Layer2String(Prim.Layer));
                                end;
                                eFillObject:
                                begin
                                    AddJSONProperty(PrimProps, 'type', 'fill');
                                    AddJSONNumber(PrimProps, 'x1', CoordToMils(Prim.x1Location));
                                    AddJSONNumber(PrimProps, 'y1', CoordToMils(Prim.y1Location));
                                    AddJSONNumber(PrimProps, 'x2', CoordToMils(Prim.x2Location));
                                    AddJSONNumber(PrimProps, 'y2', CoordToMils(Prim.y2Location));
                                    AddJSONNumber(PrimProps, 'rotation', Prim.Rotation);
                                    AddJSONProperty(PrimProps, 'layer', Layer2String(Prim.Layer));
                                end;
                                eTextObject:
                                begin
                                    AddJSONProperty(PrimProps, 'type', 'text');
                                    AddJSONProperty(PrimProps, 'text', Prim.Text);
                                    AddJSONNumber(PrimProps, 'x', CoordToMils(Prim.XLocation));
                                    AddJSONNumber(PrimProps, 'y', CoordToMils(Prim.YLocation));
                                    AddJSONNumber(PrimProps, 'size', CoordToMils(Prim.Size));
                                    AddJSONNumber(PrimProps, 'width', CoordToMils(Prim.Width));
                                    AddJSONNumber(PrimProps, 'rotation', Prim.Rotation);
                                    AddJSONProperty(PrimProps, 'layer', Layer2String(Prim.Layer));
                                    AddJSONBoolean(PrimProps, 'mirror', Prim.MirrorFlag);
                                    AddJSONBoolean(PrimProps, 'ttf', Prim.UseTTFonts);
                                end;
                                eRegionObject:
                                begin
                                    AddJSONProperty(PrimProps, 'type', 'region');
                                    AddJSONProperty(PrimProps, 'layer', Layer2String(Prim.Layer));
                                    AddJSONInteger(PrimProps, 'kind', Prim.Kind);
                                    PointsArray := TStringList.Create;
                                    try
                                        for V := 1 to Prim.MainContour.Count do
                                        begin
                                            PProps := TStringList.Create;
                                            try
                                                AddJSONNumber(PProps, 'x', CoordToMils(Prim.MainContour.x[V]));
                                                AddJSONNumber(PProps, 'y', CoordToMils(Prim.MainContour.y[V]));
                                                PointsArray.Add(BuildJSONObject(PProps, 3));
                                            finally
                                                PProps.Free;
                                            end;
                                        end;
                                        PrimProps.Add(BuildJSONArray(PointsArray, 'vertices', 2));
                                    finally
                                        PointsArray.Free;
                                    end;
                                    AddJSONInteger(PrimProps, 'hole_count', Prim.HoleCount);
                                end;
                                eViaObject:
                                begin
                                    AddJSONProperty(PrimProps, 'type', 'via');
                                    AddJSONNumber(PrimProps, 'x', CoordToMils(Prim.x));
                                    AddJSONNumber(PrimProps, 'y', CoordToMils(Prim.y));
                                    AddJSONNumber(PrimProps, 'size', CoordToMils(Prim.Size));
                                    AddJSONNumber(PrimProps, 'hole_size', CoordToMils(Prim.HoleSize));
                                    AddJSONProperty(PrimProps, 'low_layer', Layer2String(Prim.LowLayer));
                                    AddJSONProperty(PrimProps, 'high_layer', Layer2String(Prim.HighLayer));
                                end;
                                eComponentBodyObject:
                                    // 3D bodies are models, not 2D primitives -
                                    // excluded from the graphics round-trip
                                    AddJSONProperty(PrimProps, 'type', '');
                            else
                            begin
                                AddJSONProperty(PrimProps, 'type', 'unknown');
                                AddJSONInteger(PrimProps, 'object_id', Prim.ObjectId);
                            end;
                            end;

                            if (PrimProps.Count > 0) then
                                if (Pos('"type": ""', PrimProps[0]) = 0) then
                                    PrimsArray.Add(BuildJSONObject(PrimProps, 1));
                          except
                            PrimProps.Clear;
                            AddJSONProperty(PrimProps, 'type', 'unreadable');
                            PrimsArray.Add(BuildJSONObject(PrimProps, 1));
                          end;
                        finally
                            PrimProps.Free;
                        end;

                        Prim := GrpIter.NextPCBObject;
                    end;
                    LibComp.GroupIterator_Destroy(GrpIter);

                    FPProps.Add(BuildJSONArray(PrimsArray, 'primitives', 1));

                    if (FootprintName = '*') then
                        FPArray.Add(BuildJSONObject(FPProps, 1))
                    else
                        for i := 0 to FPProps.Count - 1 do
                            ResultProps.Add(FPProps[i]);
                finally
                    FPProps.Free;
                    PrimsArray.Free;
                end;
            end;
        end;

        if (FootprintName = '') or (FootprintName = '*') then
        begin
            AddJSONInteger(ResultProps, 'footprint_count', FPArray.Count);
            ResultProps.Add(BuildJSONArray(FPArray, 'footprints', 1));
        end
        else if not Found then
        begin
            Result := 'ERROR: Footprint not found in library: ' + FootprintName;
            Exit;
        end;

        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := WriteJSONToFile(OutputLines, ROOT_DIR + '\temp_footprint_primitives.json');
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
        FPArray.Free;
    end;
end;


// Function to get all unique net names from the current PCB document
function GetAllNets(ROOT_DIR: String): String;
var
    Board       : IPCB_Board;
    Net         : IPCB_Net;
    Iterator    : IPCB_BoardIterator;
    NetsArray   : TStringList; 
    OutputLines : TStringList;
begin
    // Initialize empty array result in case no board is found
    Result := '[]';
    
    // Retrieve the current board
    Board := GetBoardSafe(0);
    if Board = nil then Exit;

    // Create array for storing unique nets
    NetsArray := TStringList.Create;
    // Set Duplicates property to prevent duplicate net names
    NetsArray.Duplicates := dupIgnore;
    NetsArray.Sorted := True;
    
    try
        // Create the iterator that will look for Net objects only
        Iterator := Board.BoardIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(eNetObject));
        Iterator.AddFilter_LayerSet(AllLayers);
        Iterator.AddFilter_Method(eProcessAll);

        // Search for Net objects and get their Net Name values
        Net := Iterator.FirstPCBObject;
        while (Net <> nil) do
        begin
            // Add each net name to the list, duplicates will be ignored
            NetsArray.Add('"' + JSONEscapeString(Net.Name) + '"');
            Net := Iterator.NextPCBObject;
        end;
        Board.BoardIterator_Destroy(Iterator);
        
        // Build the final JSON array
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONArray(NetsArray);
            Result := WriteJSONToFile(OutputLines, ROOT_DIR+'\temp_nets_data.json');
        finally
            OutputLines.Free;
        end;
    finally
        NetsArray.Free;
    end;
end;

// Function to create a net class and add nets to it
function CreateNetClass(ClassName: String; NetNames: TStringList): String;
var
    Board       : IPCB_Board;
    ClassExists : Boolean;
    NetClass    : IPCB_ObjectClass;
    ClassIterator : IPCB_BoardIterator;
    i           : Integer;
    ResultProps : TStringList;
    AddedCount  : Integer;
    OutputLines : TStringList;
begin
    // Initialize result
    ResultProps := TStringList.Create;
    AddedCount := 0;
    ClassExists := False;
    
    try
        // Retrieve the current board
        Board := GetBoardSafe(0);
        if (Board = nil) then
        begin
            AddJSONBoolean(ResultProps, 'success', False);
            AddJSONProperty(ResultProps, 'error', 'No PCB document is currently active');
            
            OutputLines := TStringList.Create;
            try
                OutputLines.Text := BuildJSONObject(ResultProps);
                Result := OutputLines.Text;
            finally
                OutputLines.Free;
            end;
            Exit;
        end;
        
        // Search for existing class with the same name
        ClassIterator := Board.BoardIterator_Create;
        ClassIterator.SetState_FilterAll;
        ClassIterator.AddFilter_ObjectSet(MkSet(eClassObject));
        
        NetClass := ClassIterator.FirstPCBObject;
        while (NetClass <> nil) do
        begin
            if (NetClass.MemberKind = eClassMemberKind_Net) and (NetClass.Name = ClassName) then
            begin
                ClassExists := True;
                Break;
            end;
            NetClass := ClassIterator.NextPCBObject;
        end;
        
        // If class doesn't exist, create it and add members before registering it on the board
        // (matches Altium's documented CreateANewNetClass example exactly - AddMemberByName
        // is called as a bare statement, not as a boolean-returning function call)
        if not ClassExists then
        begin
            PCBServer.PreProcess;
            NetClass := PCBServer.PCBClassFactoryByClassMember(eClassMemberKind_Net);
            NetClass.SuperClass := False;
            NetClass.Name := ClassName;
            for i := 0 to NetNames.Count - 1 do
            begin
                NetClass.AddMemberByName(NetNames[i]);
                AddedCount := AddedCount + 1;
            end;
            Board.AddPCBObject(NetClass);
            PCBServer.PostProcess;
        end
        else
        begin
            // Class already exists on the board - add nets to it directly
            PCBServer.PreProcess;
            for i := 0 to NetNames.Count - 1 do
            begin
                NetClass.AddMemberByName(NetNames[i]);
                AddedCount := AddedCount + 1;
            end;
            PCBServer.PostProcess;
        end;

        // Clean up iterator
        Board.BoardIterator_Destroy(ClassIterator);
        
        // Build result JSON
        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'class_name', ClassName);
        AddJSONBoolean(ResultProps, 'class_created', not ClassExists);
        AddJSONInteger(ResultProps, 'nets_added', AddedCount);
        
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;

// Function to get detailed layer stackup information
function GetPCBLayerStackup(ROOT_DIR): String;
var
    Board           : IPCB_Board;
    LayerIterator   : IPCB_LayerObjectIterator;
    LayerObject     : IPCB_LayerObject;
    StackupArray    : TStringList;
    LayerProps      : TStringList;
    OutputLines     : TStringList;
    TotalThickness  : Double;
    LayerCount      : Integer;
begin
    Result := '';

    // Retrieve the current board
    Board := GetBoardSafe(0);
    if (Board = nil) then
    begin
        Result := '{"error": "No PCB document is currently active"}';
        Exit;
    end;

    // Create arrays for stackup data
    StackupArray := TStringList.Create;
    TotalThickness := 0;
    LayerCount := 0;
    
    try
        // Get the electrical layer iterator
        LayerIterator := Board.ElectricalLayerIterator;
        
        // Process each electrical layer
        while LayerIterator.Next do
        begin
            LayerObject := LayerIterator.LayerObject;
            
            // Create layer properties
            LayerProps := TStringList.Create;
            try
                // Basic layer information
                AddJSONProperty(LayerProps, 'layer_name', LayerObject.Name);
                AddJSONProperty(LayerProps, 'layer_id', Layer2String(LayerObject.LayerID));
                AddJSONProperty(LayerProps, 'material_type', 'Copper');
                AddJSONNumber(LayerProps, 'copper_thickness_mils', LayerObject.CopperThickness / 10000);
                AddJSONNumber(LayerProps, 'copper_thickness_um', LayerObject.CopperThickness / 254);
                
                // Add copper thickness to total
                TotalThickness := TotalThickness + (LayerObject.CopperThickness / 10000);
                
                // Dielectric information (if present)
                if LayerObject.Dielectric.DielectricType <> eNoDielectric then
                begin
                    case LayerObject.Dielectric.DielectricType of
                        eCore: AddJSONProperty(LayerProps, 'dielectric_type', 'Core');
                        ePrePreg: AddJSONProperty(LayerProps, 'dielectric_type', 'PrePreg');
                        eSurfaceMaterial: AddJSONProperty(LayerProps, 'dielectric_type', 'Surface Material');
                    else
                        AddJSONProperty(LayerProps, 'dielectric_type', 'Unknown');
                    end;
                    
                    AddJSONProperty(LayerProps, 'dielectric_material', LayerObject.Dielectric.DielectricMaterial);
                    AddJSONNumber(LayerProps, 'dielectric_height_mils', LayerObject.Dielectric.DielectricHeight / 10000);
                    AddJSONNumber(LayerProps, 'dielectric_height_um', LayerObject.Dielectric.DielectricHeight / 254);
                    AddJSONNumber(LayerProps, 'dielectric_constant', LayerObject.Dielectric.DielectricConstant);
                    
                    // Add dielectric thickness to total
                    TotalThickness := TotalThickness + (LayerObject.Dielectric.DielectricHeight / 10000);
                end
                else
                begin
                    AddJSONProperty(LayerProps, 'dielectric_type', 'No Dielectric');
                    AddJSONProperty(LayerProps, 'dielectric_material', '');
                    AddJSONNumber(LayerProps, 'dielectric_height_mils', 0);
                    AddJSONNumber(LayerProps, 'dielectric_height_um', 0);
                    AddJSONNumber(LayerProps, 'dielectric_constant', 0);
                end;
                
                // Add layer order
                AddJSONInteger(LayerProps, 'layer_order', LayerCount + 1);
                
                // Add to stackup array
                StackupArray.Add(BuildJSONObject(LayerProps, 1));
                LayerCount := LayerCount + 1;
            finally
                LayerProps.Free;
            end;
        end;
        
        // Create final stackup object with summary
        LayerProps := TStringList.Create;
        try
            AddJSONInteger(LayerProps, 'total_layers', LayerCount);
            AddJSONNumber(LayerProps, 'total_thickness_mils', TotalThickness);
            AddJSONNumber(LayerProps, 'total_thickness_mm', TotalThickness * 0.0254);
            AddJSONProperty(LayerProps, 'board_name', ExtractFileName(Board.FileName));
            
            // Add the layers array
            LayerProps.Add(BuildJSONArray(StackupArray, 'layers'));
            
            // Build the final JSON
            OutputLines := TStringList.Create;
            try
                OutputLines.Text := BuildJSONObject(LayerProps);
                Result := WriteJSONToFile(OutputLines, ROOT_DIR+'\temp_stackup_data.json');
            finally
                OutputLines.Free;
            end;
        finally
            LayerProps.Free;
        end;
    finally
        StackupArray.Free;
    end;
end;

// Function to get all layer information from the PCB
function GetPCBLayers(ROOT_DIR: String): String;
var
    Board           : IPCB_Board;
    TheLayerStack   : IPCB_LayerStack_V7;
    LayerObj        : IPCB_LayerObject;
    MechLayer       : IPCB_MechanicalLayer;
    AllLayersArray  : TStringList;
    CopperArray     : TStringList;
    MechArray       : TStringList;
    OtherArray      : TStringList;
    LayerProps      : TStringList;
    i               : Integer;
    OutputLines     : TStringList;
begin
    Result := '';

    // Retrieve the current board
    Board := GetBoardSafe(0);
    if (Board = nil) then
    begin
        Result := '[]';
        Exit;
    end;
    
    // Get the layer stack
    TheLayerStack := Board.LayerStack_V7;
    if (TheLayerStack = nil) then
    begin
        Result := '[]';
        Exit;
    end;

    // Create arrays for different layer categories
    AllLayersArray := TStringList.Create;
    CopperArray := TStringList.Create;
    MechArray := TStringList.Create;
    OtherArray := TStringList.Create;
    
    try
        // Process copper (electrical) layers
        LayerObj := TheLayerStack.FirstLayer;
        while (LayerObj <> nil) do
        begin
            // Create layer properties
            LayerProps := TStringList.Create;
            try
                // Add properties
                AddJSONProperty(LayerProps, 'name', LayerObj.Name);
                AddJSONProperty(LayerProps, 'layer_id', IntToStr(LayerObj.V6_LayerID));
                AddJSONProperty(LayerProps, 'layer_type', 'copper');

                if LayerSet.SignalLayers.Contains(LayerObj.V6_LayerID) then
                    AddJSONProperty(LayerProps, 'is_signal', 'true', False)
                else
                    AddJSONProperty(LayerProps, 'is_signal', 'false', False);

                if not LayerSet.SignalLayers.Contains(LayerObj.V6_LayerID) then
                    AddJSONProperty(LayerProps, 'is_plane', 'true', False)
                else
                    AddJSONProperty(LayerProps, 'is_plane', 'false', False);

                AddJSONBoolean(LayerProps, 'is_displayed', LayerObj.IsDisplayed[Board]);
                AddJSONBoolean(LayerProps, 'is_enabled', True);
                AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[LayerObj.LayerID]));
                
                // Add to copper array
                CopperArray.Add(BuildJSONObject(LayerProps, 1));
            finally
                LayerProps.Free;
            end;
            
            LayerObj := TheLayerStack.NextLayer(LayerObj);
        end;
        
        // Process mechanical layers
        for i := 1 to 32 do
        begin
            MechLayer := TheLayerStack.LayerObject_V7[ILayer.MechanicalLayer(i)];
            
            if MechLayer.MechanicalLayerEnabled then
            begin
                // Create layer properties
                LayerProps := TStringList.Create;
                try
                    // Add properties
                    AddJSONProperty(LayerProps, 'name', MechLayer.Name);
                    AddJSONProperty(LayerProps, 'layer_id', IntToStr(MechLayer.V6_LayerID));
                    AddJSONProperty(LayerProps, 'layer_type', 'mechanical');
                    AddJSONProperty(LayerProps, 'mechanical_number', IntToStr(i));
                    AddJSONBoolean(LayerProps, 'is_displayed', MechLayer.IsDisplayed[Board]);
                    AddJSONBoolean(LayerProps, 'is_enabled', MechLayer.MechanicalLayerEnabled);
                    AddJSONBoolean(LayerProps, 'link_to_sheet', MechLayer.LinkToSheet);
                    AddJSONBoolean(LayerProps, 'is_paired', Board.MechanicalPairs.LayerUsed(ILayer.MechanicalLayer(i)));
                    AddJSONProperty(LayerProps, 'color', ColorToString(PCBServer.SystemOptions.LayerColors[MechLayer.V6_LayerID]));
                    
                    // If layer is paired, add the pair information
                    if Board.MechanicalPairs.LayerUsed(ILayer.MechanicalLayer(i)) then
                    begin
                        // Could add pair info here if Altium API provides it
                    end;
                    
                    // Add to mechanical array
                    MechArray.Add(BuildJSONObject(LayerProps, 1));
                finally
                    LayerProps.Free;
                end;
            end;
        end;
        
        // Process other special layers
        // Top Overlay
        LayerProps := TStringList.Create;
        try
            AddJSONProperty(LayerProps, 'name', 'Top Overlay');
            AddJSONProperty(LayerProps, 'layer_id', IntToStr(String2Layer('Top Overlay')));
            AddJSONProperty(LayerProps, 'layer_type', 'special');
            AddJSONProperty(LayerProps, 'special_type', 'overlay');
            AddJSONBoolean(LayerProps, 'is_displayed', Board.LayerIsDisplayed[String2Layer('Top Overlay')]);
            AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[String2Layer('Top Overlay')]));
            OtherArray.Add(BuildJSONObject(LayerProps, 1));
        finally
            LayerProps.Free;
        end;
        
        // Bottom Overlay
        LayerProps := TStringList.Create;
        try
            AddJSONProperty(LayerProps, 'name', 'Bottom Overlay');
            AddJSONProperty(LayerProps, 'layer_id', IntToStr(String2Layer('Bottom Overlay')));
            AddJSONProperty(LayerProps, 'layer_type', 'special');
            AddJSONProperty(LayerProps, 'special_type', 'overlay');
            AddJSONBoolean(LayerProps, 'is_displayed', Board.LayerIsDisplayed[String2Layer('Bottom Overlay')]);
            AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[String2Layer('Bottom Overlay')]));
            OtherArray.Add(BuildJSONObject(LayerProps, 1));
        finally
            LayerProps.Free;
        end;
        
        // Top Solder Mask
        LayerProps := TStringList.Create;
        try
            AddJSONProperty(LayerProps, 'name', 'Top Solder Mask');
            AddJSONProperty(LayerProps, 'layer_id', IntToStr(String2Layer('Top Solder Mask')));
            AddJSONProperty(LayerProps, 'layer_type', 'special');
            AddJSONProperty(LayerProps, 'special_type', 'solder_mask');
            AddJSONBoolean(LayerProps, 'is_displayed', Board.LayerIsDisplayed[String2Layer('Top Solder Mask')]);
            AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[String2Layer('Top Solder Mask')]));
            OtherArray.Add(BuildJSONObject(LayerProps, 1));
        finally
            LayerProps.Free;
        end;
        
        // Bottom Solder Mask
        LayerProps := TStringList.Create;
        try
            AddJSONProperty(LayerProps, 'name', 'Bottom Solder Mask');
            AddJSONProperty(LayerProps, 'layer_id', IntToStr(String2Layer('Bottom Solder Mask')));
            AddJSONProperty(LayerProps, 'layer_type', 'special');
            AddJSONProperty(LayerProps, 'special_type', 'solder_mask');
            AddJSONBoolean(LayerProps, 'is_displayed', Board.LayerIsDisplayed[String2Layer('Bottom Solder Mask')]);
            AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[String2Layer('Bottom Solder Mask')]));
            OtherArray.Add(BuildJSONObject(LayerProps, 1));
        finally
            LayerProps.Free;
        end;
        
        // Top Paste
        LayerProps := TStringList.Create;
        try
            AddJSONProperty(LayerProps, 'name', 'Top Paste');
            AddJSONProperty(LayerProps, 'layer_id', IntToStr(String2Layer('Top Paste')));
            AddJSONProperty(LayerProps, 'layer_type', 'special');
            AddJSONProperty(LayerProps, 'special_type', 'paste');
            AddJSONBoolean(LayerProps, 'is_displayed', Board.LayerIsDisplayed[String2Layer('Top Paste')]);
            AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[String2Layer('Top Paste')]));
            OtherArray.Add(BuildJSONObject(LayerProps, 1));
        finally
            LayerProps.Free;
        end;
        
        // Bottom Paste
        LayerProps := TStringList.Create;
        try
            AddJSONProperty(LayerProps, 'name', 'Bottom Paste');
            AddJSONProperty(LayerProps, 'layer_id', IntToStr(String2Layer('Bottom Paste')));
            AddJSONProperty(LayerProps, 'layer_type', 'special');
            AddJSONProperty(LayerProps, 'special_type', 'paste');
            AddJSONBoolean(LayerProps, 'is_displayed', Board.LayerIsDisplayed[String2Layer('Bottom Paste')]);
            AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[String2Layer('Bottom Paste')]));
            OtherArray.Add(BuildJSONObject(LayerProps, 1));
        finally
            LayerProps.Free;
        end;
        
        // Drill Guide
        LayerProps := TStringList.Create;
        try
            AddJSONProperty(LayerProps, 'name', 'Drill Guide');
            AddJSONProperty(LayerProps, 'layer_id', IntToStr(String2Layer('Drill Guide')));
            AddJSONProperty(LayerProps, 'layer_type', 'special');
            AddJSONProperty(LayerProps, 'special_type', 'drill');
            AddJSONBoolean(LayerProps, 'is_displayed', Board.LayerIsDisplayed[String2Layer('Drill Guide')]);
            AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[String2Layer('Drill Guide')]));
            OtherArray.Add(BuildJSONObject(LayerProps, 1));
        finally
            LayerProps.Free;
        end;
        
        // Drill Drawing
        LayerProps := TStringList.Create;
        try
            AddJSONProperty(LayerProps, 'name', 'Drill Drawing');
            AddJSONProperty(LayerProps, 'layer_id', IntToStr(String2Layer('Drill Drawing')));
            AddJSONProperty(LayerProps, 'layer_type', 'special');
            AddJSONProperty(LayerProps, 'special_type', 'drill');
            AddJSONBoolean(LayerProps, 'is_displayed', Board.LayerIsDisplayed[String2Layer('Drill Drawing')]);
            AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[String2Layer('Drill Drawing')]));
            OtherArray.Add(BuildJSONObject(LayerProps, 1));
        finally
            LayerProps.Free;
        end;
        
        // Multi Layer
        LayerProps := TStringList.Create;
        try
            AddJSONProperty(LayerProps, 'name', 'Multi Layer');
            AddJSONProperty(LayerProps, 'layer_id', IntToStr(String2Layer('Multi Layer')));
            AddJSONProperty(LayerProps, 'layer_type', 'special');
            AddJSONProperty(LayerProps, 'special_type', 'multi');
            AddJSONBoolean(LayerProps, 'is_displayed', Board.LayerIsDisplayed[String2Layer('Multi Layer')]);
            AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[String2Layer('Multi Layer')]));
            OtherArray.Add(BuildJSONObject(LayerProps, 1));
        finally
            LayerProps.Free;
        end;
        
        // Keep Out Layer
        LayerProps := TStringList.Create;
        try
            AddJSONProperty(LayerProps, 'name', 'Keep Out Layer');
            AddJSONProperty(LayerProps, 'layer_id', IntToStr(String2Layer('Keep Out Layer')));
            AddJSONProperty(LayerProps, 'layer_type', 'special');
            AddJSONProperty(LayerProps, 'special_type', 'keepout');
            AddJSONBoolean(LayerProps, 'is_displayed', Board.LayerIsDisplayed[String2Layer('Keep Out Layer')]);
            AddJSONProperty(LayerProps, 'color', ColorToString(Board.LayerColor[String2Layer('Keep Out Layer')]));
            OtherArray.Add(BuildJSONObject(LayerProps, 1));
        finally
            LayerProps.Free;
        end;
        
        // Add additional info for the complete layer response
        LayerProps := TStringList.Create;
        try
            // Add summary information
            AddJSONInteger(LayerProps, 'copper_layers_count', TheLayerStack.LayersInStackCount);
            AddJSONInteger(LayerProps, 'signal_layers_count', TheLayerStack.SignalLayerCount);
            AddJSONInteger(LayerProps, 'internal_planes_count', TheLayerStack.LayersInStackCount - TheLayerStack.SignalLayerCount);
            
            // Get the number of enabled mechanical layers
            i := 0;
            for i := 1 to 32 do
                if TheLayerStack.LayerObject_V7[ILayer.MechanicalLayer(i)].MechanicalLayerEnabled then
                    i := i + 1;
            AddJSONInteger(LayerProps, 'mechanical_layers_count', i);
            
            // Add the layer arrays
            LayerProps.Add(BuildJSONArray(CopperArray, 'copper_layers'));
            LayerProps.Add(BuildJSONArray(MechArray, 'mechanical_layers'));
            LayerProps.Add(BuildJSONArray(OtherArray, 'special_layers'));
            
            // Build the final JSON
            OutputLines := TStringList.Create;
            try
                OutputLines.Text := BuildJSONObject(LayerProps);
                Result := WriteJSONToFile(OutputLines, ROOT_DIR+'\temp_layers_data.json');
            finally
                OutputLines.Free;
            end;
        finally
            LayerProps.Free;
        end;
    finally
        AllLayersArray.Free;
        CopperArray.Free;
        MechArray.Free;
        OtherArray.Free;
    end;
end;

// Function to set layer visibility (only specified layers visible)
// Function to set layer visibility with two modes:
// - visible=true: Show only specified layers, hide all others
// - visible=false: Hide specified layers, leave others unchanged
function SetPCBLayerVisibility(LayerNamesList: TStringList; Visible: Boolean): String;
var
    Board          : IPCB_Board;
    TheLayerStack  : IPCB_LayerStack_V7;
    LayerObj       : IPCB_LayerObject;
    MechLayer      : IPCB_MechanicalLayer;
    ResultProps    : TStringList;
    OutputLines    : TStringList;
    i, j           : Integer;
    LayerName      : String;
    LayerID        : TLayer;
    FoundCount     : Integer;
    NotFoundList   : TStringList;
    FoundLayers    : TStringList;
begin
    // Retrieve the current board
    Board := GetBoardSafe(0);
    if (Board = nil) then
    begin
        Result := '{"success": false, "error": "No PCB document is currently active"}';
        Exit;
    end;
    
    // Get the layer stack
    TheLayerStack := Board.LayerStack_V7;
    if (TheLayerStack = nil) then
    begin
        Result := '{"success": false, "error": "Failed to retrieve layer stack"}';
        Exit;
    end;
    
    // Create lists for tracking results
    ResultProps := TStringList.Create;
    NotFoundList := TStringList.Create;
    FoundLayers := TStringList.Create;
    FoundCount := 0;
    
    try
        // First phase: identify all specified layers
        for i := 0 to LayerNamesList.Count - 1 do
        begin
            LayerName := LayerNamesList[i];
            
            // Try to find the layer by name
            // First check special layers (since they have specific names)
            if (LayerName = 'Top Overlay') or 
               (LayerName = 'Bottom Overlay') or
               (LayerName = 'Top Solder Mask') or
               (LayerName = 'Bottom Solder Mask') or
               (LayerName = 'Top Paste') or
               (LayerName = 'Bottom Paste') or
               (LayerName = 'Drill Guide') or
               (LayerName = 'Drill Drawing') or
               (LayerName = 'Multi Layer') or
               (LayerName = 'Keep Out Layer') then
            begin
                // Get layer ID from name
                LayerID := String2Layer(LayerName);
                if (LayerID <> eNoLayer) then
                begin
                    FoundLayers.Add(IntToStr(LayerID));
                    FoundCount := FoundCount + 1;
                end
                else
                    NotFoundList.Add('"' + JSONEscapeString(LayerName) + '"');
                
                continue;
            end;
            
            // Check copper layers
            LayerObj := TheLayerStack.FirstLayer;
            j := 1;
            
            while (LayerObj <> nil) do
            begin
                if (LayerObj.Name = LayerName) then
                begin
                    FoundLayers.Add(IntToStr(LayerObj.V6_LayerID));
                    FoundCount := FoundCount + 1;
                    break;
                end;
                
                Inc(j);
                LayerObj := TheLayerStack.NextLayer(LayerObj);
            end;
            
            // If we found the layer in copper layers, continue to next layer name
            if (LayerObj <> nil) then
                continue;
            
            // Check mechanical layers (they can have custom names)
            for j := 1 to 32 do
            begin
                MechLayer := TheLayerStack.LayerObject_V7[ILayer.MechanicalLayer(j)];
                
                if MechLayer.MechanicalLayerEnabled and (MechLayer.Name = LayerName) then
                begin
                    FoundLayers.Add(IntToStr(MechLayer.V6_LayerID));
                    FoundCount := FoundCount + 1;
                    break;
                end;
            end;
            
            // If we've checked all layer types and didn't find a match, add to not found list
            if j > 32 then
                NotFoundList.Add('"' + JSONEscapeString(LayerName) + '"');
        end;
        
        // Second phase: set visibility for all layers based on mode
        if Visible then
        begin
            // Visibility mode: show only specified layers, hide all others
            
            // For copper layers
            LayerObj := TheLayerStack.FirstLayer;
            while (LayerObj <> nil) do
            begin
                // Check if this layer is in our found list
                if (FoundLayers.IndexOf(IntToStr(LayerObj.V6_LayerID)) >= 0) then
                    LayerObj.IsDisplayed[Board] := True
                else
                    LayerObj.IsDisplayed[Board] := False;
                
                LayerObj := TheLayerStack.NextLayer(LayerObj);
            end;
            
            // For mechanical layers
            for j := 1 to 32 do
            begin
                MechLayer := TheLayerStack.LayerObject_V7[ILayer.MechanicalLayer(j)];
                
                if MechLayer.MechanicalLayerEnabled then
                begin
                    if (FoundLayers.IndexOf(IntToStr(MechLayer.V6_LayerID)) >= 0) then
                        MechLayer.IsDisplayed[Board] := True
                    else
                        MechLayer.IsDisplayed[Board] := False;
                end;
            end;
            
            // For special layers
            for j := 1 to 10 do
            begin
                case j of
                    1: LayerID := String2Layer('Top Overlay');
                    2: LayerID := String2Layer('Bottom Overlay');
                    3: LayerID := String2Layer('Top Solder Mask');
                    4: LayerID := String2Layer('Bottom Solder Mask');
                    5: LayerID := String2Layer('Top Paste');
                    6: LayerID := String2Layer('Bottom Paste');
                    7: LayerID := String2Layer('Drill Guide');
                    8: LayerID := String2Layer('Drill Drawing');
                    9: LayerID := String2Layer('Multi Layer');
                    10: LayerID := String2Layer('Keep Out Layer');
                end;
                
                if (FoundLayers.IndexOf(IntToStr(LayerID)) >= 0) then
                    Board.LayerIsDisplayed[LayerID] := True
                else
                    Board.LayerIsDisplayed[LayerID] := False;
            end;
        end
        else
        begin
            // Hide mode: only hide specified layers, leave others unchanged
            
            // For copper layers
            LayerObj := TheLayerStack.FirstLayer;
            while (LayerObj <> nil) do
            begin
                // Check if this layer is in our found list
                if (FoundLayers.IndexOf(IntToStr(LayerObj.V6_LayerID)) >= 0) then
                    LayerObj.IsDisplayed[Board] := False;
                
                LayerObj := TheLayerStack.NextLayer(LayerObj);
            end;
            
            // For mechanical layers
            for j := 1 to 32 do
            begin
                MechLayer := TheLayerStack.LayerObject_V7[ILayer.MechanicalLayer(j)];
                
                if MechLayer.MechanicalLayerEnabled then
                begin
                    if (FoundLayers.IndexOf(IntToStr(MechLayer.V6_LayerID)) >= 0) then
                        MechLayer.IsDisplayed[Board] := False;
                end;
            end;
            
            // For special layers
            for j := 1 to 10 do
            begin
                case j of
                    1: LayerID := String2Layer('Top Overlay');
                    2: LayerID := String2Layer('Bottom Overlay');
                    3: LayerID := String2Layer('Top Solder Mask');
                    4: LayerID := String2Layer('Bottom Solder Mask');
                    5: LayerID := String2Layer('Top Paste');
                    6: LayerID := String2Layer('Bottom Paste');
                    7: LayerID := String2Layer('Drill Guide');
                    8: LayerID := String2Layer('Drill Drawing');
                    9: LayerID := String2Layer('Multi Layer');
                    10: LayerID := String2Layer('Keep Out Layer');
                end;
                
                if (FoundLayers.IndexOf(IntToStr(LayerID)) >= 0) then
                    Board.LayerIsDisplayed[LayerID] := False;
            end;
        end;
        
        // Update the display
        Board.ViewManager_FullUpdate;
        Board.ViewManager_UpdateLayerTabs;
        
        // Create result JSON
        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONInteger(ResultProps, 'updated_count', FoundCount);
        
        // Add missing layers array
        if (NotFoundList.Count > 0) then
            ResultProps.Add(BuildJSONArray(NotFoundList, 'not_found_layers'))
        else
            ResultProps.Add('"not_found_layers": []');
        
        // Build final JSON
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
        NotFoundList.Free;
        FoundLayers.Free;
    end;
end;

// Function to get all PCB rules
function GetPCBRules(ROOT_DIR: String): String;
Var
    Board         : IPCB_Board;
    Rule          : IPCB_Rule;
    BoardIterator : IPCB_BoardIterator;
    RulesArray    : TStringList;
    RuleProps     : TStringList;
    OutputLines   : TStringList;
begin
    // Retrieve the current board
    Board := GetBoardSafe(0);
    if (Board = Nil) then
    begin
        Result := '[]';
        Exit;
    end;

    // Create array for rules
    RulesArray := TStringList.Create;
    
    try
        // Retrieve the iterator
        BoardIterator := Board.BoardIterator_Create;
        BoardIterator.AddFilter_ObjectSet(MkSet(eRuleObject));
        BoardIterator.AddFilter_LayerSet(AllLayers);
        BoardIterator.AddFilter_Method(eProcessAll);

        // Process each rule
        Rule := BoardIterator.FirstPCBObject;
        while (Rule <> Nil) do
        begin
            // Create rule properties
            RuleProps := TStringList.Create;
            try
                // Add rule descriptor
                AddJSONProperty(RuleProps, 'descriptor', Rule.Descriptor);
                AddJSONProperty(RuleProps, 'rule_kind', Rule.GetState_ShortDescriptorString);
                AddJSONProperty(RuleProps, 'filter1', Rule.Scope1Expression);
                AddJSONProperty(RuleProps, 'filter2', Rule.Scope2Expression);

                // Add to rules array
                RulesArray.Add(BuildJSONObject(RuleProps, 1));
            finally
                RuleProps.Free;
            end;
            
            // Move to next rule
            Rule := BoardIterator.NextPCBObject;
        end;

        // Clean up the iterator
        Board.BoardIterator_Destroy(BoardIterator);
        
        // Build the final JSON array
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONArray(RulesArray);
            Result := WriteJSONToFile(OutputLines, ROOT_DIR+'\temp_rules_data.json');
        finally
            OutputLines.Free;
        end;
    finally
        RulesArray.Free;
    end;
end;

// Function to create a new Clearance Constraint design rule
// Gap is NOT a property of the base IPCB_Rule interface - it lives on the
// IPCB_ClearanceConstraint subtype. PCBRuleFactory's result must be assigned
// directly to a variable typed as that subtype for DelphiScript to expose
// .Gap; a generic IPCB_Rule variable will not see it.
function CreatePCBClearanceRule(RuleName: String; Scope1: String; Scope2: String; GapMM: Double; NetScopeStr: String): String;
var
    Board       : IPCB_Board;
    Rule        : IPCB_Rule;
    RuleClear   : IPCB_ClearanceConstraint;
    ResultProps : TStringList;
    OutputLines : TStringList;
begin
    Board := PCBServer.GetCurrentPCBBoard;
    if (Board = nil) then
    begin
        Result := '{"success": false, "error": "No PCB document is currently active"}';
        Exit;
    end;

    ResultProps := TStringList.Create;
    try
        PCBServer.PreProcess;
        try
            RuleClear := PCBServer.PCBRuleFactory(eRule_Clearance);
            RuleClear.LayerKind := eRuleLayerKind_SameLayer;
            // Default (including when the caller passes nothing, e.g. before the MCP
            // tool schema is updated/reloaded) is DifferentNetsOnly: clearance rules
            // are about preventing shorts between unrelated nets, so checking spacing
            // on same-net copper (which is expected to touch/overlap) is not meaningful
            // and can produce spurious/confusing behavior. Pass net_scope="AnyNet" or
            // "SameNetOnly" explicitly to opt out.
            if (NetScopeStr = 'AnyNet') then
                RuleClear.NetScope := eNetScope_AnyNet
            else if (NetScopeStr = 'SameNetOnly') then
                RuleClear.NetScope := eNetScope_SameNetOnly
            else
                RuleClear.NetScope := eNetScope_DifferentNetsOnly;
            RuleClear.Gap := MMsToCoord(GapMM);

            if (RuleName <> '') then
                RuleClear.Name := RuleName;
            if (Scope1 <> '') then
                RuleClear.Scope1Expression := Scope1;
            if (Scope2 <> '') then
                RuleClear.Scope2Expression := Scope2;

            Rule := RuleClear;
            Rule.Enabled := True;

            Board.AddPCBObject(Rule);
            PCBServer.SendMessageToRobots(Board.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Rule.I_ObjectAddress);
        finally
            PCBServer.PostProcess;
        end;

        Board.ViewManager_FullUpdate;

        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'descriptor', Rule.Descriptor);
        AddJSONProperty(ResultProps, 'filter1', Rule.Scope1Expression);
        AddJSONProperty(ResultProps, 'filter2', Rule.Scope2Expression);

        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;

// Function to get all component data from the PCB
function GetAllComponentData(ROOT_DIR: String, SelectedOnly: Boolean = False): String;
var
    Board       : IPCB_Board;
    Iterator    : IPCB_BoardIterator;
    Component   : IPCB_Component;
    ComponentsArray : TStringList;
    ComponentProps : TStringList;
    Rect        : TCoordRect;
    xorigin, yorigin : Integer;
    i           : Integer;
    ComponentCount : Integer;
    OutputLines : TStringList;
begin
    // Retrieve the current board
    Board := GetBoardSafe(0);
    if (Board = nil) then
    begin
        Result := '[]';
        Exit;
    end;
    
    // Get board origin coordinates
    xorigin := Board.XOrigin;
    yorigin := Board.YOrigin;

    // Create array for components
    ComponentsArray := TStringList.Create;
    
    try
        // Create an iterator to find all components
        Iterator := Board.BoardIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(eComponentObject));
        Iterator.AddFilter_IPCB_LayerSet(LayerSet.AllLayers);
        Iterator.AddFilter_Method(eProcessAll);

        // Process each component
        Component := Iterator.FirstPCBObject;
        while (Component <> Nil) do
        begin
            // Process either all components or only selected ones
            if ((not SelectedOnly) or (SelectedOnly and Component.Selected)) then
            begin
                // Create component properties
                ComponentProps := TStringList.Create;
                try
                    // Get bounds
                    Rect := Component.BoundingRectangleNoNameComment;
                    
                    // Add properties
                    AddJSONProperty(ComponentProps, 'designator', Component.Name.Text);
                    AddJSONProperty(ComponentProps, 'name', Component.Identifier);
                    AddJSONProperty(ComponentProps, 'description', Component.SourceDescription);
                    AddJSONProperty(ComponentProps, 'footprint', Component.Pattern);
                    AddJSONProperty(ComponentProps, 'layer', Layer2String(Component.Layer));
                    AddJSONNumber(ComponentProps, 'x', CoordToMils(Component.x - xorigin));
                    AddJSONNumber(ComponentProps, 'y', CoordToMils(Component.y - yorigin));
                    AddJSONNumber(ComponentProps, 'width', CoordToMils(Rect.Right - Rect.Left));
                    AddJSONNumber(ComponentProps, 'height', CoordToMils(Rect.Top - Rect.Bottom));
                    AddJSONNumber(ComponentProps, 'rotation', Component.Rotation);

                    // Add to components array
                    ComponentsArray.Add(BuildJSONObject(ComponentProps, 1));
                finally
                    ComponentProps.Free;
                end;
            end;
            
            // Move to next component
            Component := Iterator.NextPCBObject;
        end;

        // Clean up the iterator
        Board.BoardIterator_Destroy(Iterator);
        
        // Build the final JSON array
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONArray(ComponentsArray);
            Result := WriteJSONToFile(OutputLines, ROOT_DIR+'\temp_component_data.json');
        finally
            OutputLines.Free;
        end;
    finally
        ComponentsArray.Free;
    end;
end;

// Example refactored function using the new JSON utilities
function GetSelectedComponentsCoordinates(ROOT_DIR: String): String;
var
    Board       : IPCB_Board;
    Component   : IPCB_Component;
    Rect        : TCoordRect;
    xorigin, yorigin : Integer;
    ComponentsArray : TStringList;
    ComponentProps : TStringList;
    OutputLines : TStringList;
    i : Integer;
begin
    Result := '';

    // Retrieve the current board
    Board := GetBoardSafe(0);
    if Board = nil then Exit;

    // Get board origin coordinates
    xorigin := Board.XOrigin;
    yorigin := Board.YOrigin;

    // Create output and components array
    OutputLines := TStringList.Create;
    ComponentsArray := TStringList.Create;
    
    try
        // Process each selected component
        for i := 0 to Board.SelectecObjectCount - 1 do
        begin
            // Only process selected components
            if Board.SelectecObject[i].ObjectId = eComponentObject then
            begin
                // Cast to component type
                Component := Board.SelectecObject[i];
                
                // Get component bounds
                Rect := Component.BoundingRectangleNoNameComment;
                
                // Create component properties
                ComponentProps := TStringList.Create;
                try
                    // Add component properties
                    AddJSONProperty(ComponentProps, 'designator', Component.Name.Text);
                    AddJSONProperty(ComponentProps, 'layer', Layer2String(Component.Layer));
                    AddJSONProperty(ComponentProps, 'footprint', Component.Pattern);
                    AddJSONNumber(ComponentProps, 'x', CoordToMils(Component.x - xorigin));
                    AddJSONNumber(ComponentProps, 'y', CoordToMils(Component.y - yorigin));
                    AddJSONNumber(ComponentProps, 'width', CoordToMils(Rect.Right - Rect.Left));
                    AddJSONNumber(ComponentProps, 'height', CoordToMils(Rect.Top - Rect.Bottom));
                    AddJSONNumber(ComponentProps, 'rotation', Component.Rotation);
                    
                    // Add component JSON to array
                    ComponentsArray.Add(BuildJSONObject(ComponentProps, 1));
                finally
                    ComponentProps.Free;
                end;
            end;
        end;
        
        // If components found, build array
        if ComponentsArray.Count > 0 then
            Result := BuildJSONArray(ComponentsArray)
        else
            Result := '[]';
            
        // For consistency with existing code, write to file and read back
        OutputLines.Text := Result;
        Result := WriteJSONToFile(OutputLines, ROOT_DIR+'\temp_selected_components.json');
    finally
        ComponentsArray.Free;
        OutputLines.Free;
    end;
end;

// Function to get pin data for specified components
function GetComponentPinsFromList(ROOT_DIR: String; DesignatorsList: TStringList): String;
var
    Board           : IPCB_Board;
    Component       : IPCB_Component;
    ComponentsArray : TStringList;
    CompProps       : TStringList;
    PinsArray       : TStringList;
    GrpIter         : IPCB_GroupIterator;
    Pad             : IPCB_Pad;
    NetName         : String;
    xorigin, yorigin : Integer;
    PinProps        : TStringList;
    PinCount, PinsProcessed : Integer;
    Designator      : String;
    i               : Integer;
    OutputLines     : TStringList;
    CompX, CompY    : Double;
    CompRad         : Double;
    AbsDX, AbsDY    : Double;
    RelDX, RelDY    : Double;
begin
    // Retrieve the current board
    Board := GetBoardSafe(0);
    if (Board = nil) then
    begin
        Result := '[]';
        Exit;
    end;
    
    // Get board origin coordinates
    xorigin := Board.XOrigin;
    yorigin := Board.YOrigin;

    // Create array for components
    ComponentsArray := TStringList.Create;
    
    try
        // Process each designator
        for i := 0 to DesignatorsList.Count - 1 do
        begin
            Designator := Trim(DesignatorsList[i]);
            
            // Use direct function to get component by designator
            Component := Board.GetPcbComponentByRefDes(Designator);
            
            if (Component <> Nil) then
            begin
                // Create component properties
                CompProps := TStringList.Create;
                PinsArray := TStringList.Create;
                
                try
                    // Add designator to component
                    AddJSONProperty(CompProps, 'designator', Component.Name.Text);

                    // Component placement info so pin data is self-contained
                    CompX := CoordToMils(Component.x - xorigin);
                    CompY := CoordToMils(Component.y - yorigin);
                    CompRad := Component.Rotation * Pi / 180;
                    AddJSONNumber(CompProps, 'x', CompX);
                    AddJSONNumber(CompProps, 'y', CompY);
                    AddJSONNumber(CompProps, 'rotation', Component.Rotation);
                    AddJSONProperty(CompProps, 'layer', Layer2String(Component.Layer));

                    // Create pad iterator
                    GrpIter := Component.GroupIterator_Create;
                    GrpIter.SetState_FilterAll;
                    GrpIter.AddFilter_ObjectSet(MkSet(ePadObject));
                    
                    // Count pins
                    PinCount := 0;
                    Pad := GrpIter.FirstPCBObject;
                    while (Pad <> Nil) do
                    begin
                        if Pad.InComponent then
                            PinCount := PinCount + 1;
                        Pad := GrpIter.NextPCBObject;
                    end;
                    
                    // Reset iterator
                    Component.GroupIterator_Destroy(GrpIter);
                    GrpIter := Component.GroupIterator_Create;
                    GrpIter.SetState_FilterAll;
                    GrpIter.AddFilter_ObjectSet(MkSet(ePadObject));
                    
                    // Process each pad
                    PinsProcessed := 0;
                    Pad := GrpIter.FirstPCBObject;
                    while (Pad <> Nil) do
                    begin
                        if Pad.InComponent then
                        begin
                            // Get net name if connected
                            if (Pad.Net <> Nil) then
                                NetName := Pad.Net.Name
                            else
                                NetName := '';
                                
                            // Create pin properties
                            PinProps := TStringList.Create;
                            try
                                AddJSONProperty(PinProps, 'name', Pad.Name);
                                AddJSONProperty(PinProps, 'net', NetName);
                                AddJSONNumber(PinProps, 'x', CoordToMils(Pad.x - xorigin));
                                AddJSONNumber(PinProps, 'y', CoordToMils(Pad.y - yorigin));

                                // Pad offset from the component origin in the
                                // footprint's rotation-0 frame: un-rotate the
                                // current offset, and un-mirror X for parts on
                                // the bottom side. Predicted pad position after
                                // placement = origin + (mirror-x if bottom,
                                // then rotate CCW by rotation) applied to dx/dy.
                                AbsDX := CoordToMils(Pad.x - xorigin) - CompX;
                                AbsDY := CoordToMils(Pad.y - yorigin) - CompY;
                                RelDX := AbsDX * Cos(CompRad) + AbsDY * Sin(CompRad);
                                RelDY := -AbsDX * Sin(CompRad) + AbsDY * Cos(CompRad);
                                if (Component.Layer = eBottomLayer) then
                                begin
                                    RelDX := -(AbsDX * Cos(CompRad) - AbsDY * Sin(CompRad));
                                    RelDY := AbsDX * Sin(CompRad) + AbsDY * Cos(CompRad);
                                end;
                                // Round away trig noise (0.0001 mil resolution)
                                RelDX := Round(RelDX * 10000) / 10000;
                                RelDY := Round(RelDY * 10000) / 10000;
                                AddJSONNumber(PinProps, 'dx', RelDX);
                                AddJSONNumber(PinProps, 'dy', RelDY);

                                AddJSONNumber(PinProps, 'rotation', Pad.Rotation);
                                AddJSONProperty(PinProps, 'layer', Layer2String(Pad.Layer));
                                AddJSONNumber(PinProps, 'width', CoordToMils(Pad.XSizeOnLayer[Pad.Layer]));
                                AddJSONNumber(PinProps, 'height', CoordToMils(Pad.YSizeOnLayer[Pad.Layer]));
                                AddJSONProperty(PinProps, 'shape', ShapeToString(Pad.ShapeOnLayer[Pad.Layer]));
                                
                                // Add to pins array
                                PinsArray.Add(BuildJSONObject(PinProps, 3));
                                
                                // Increment counter
                                PinsProcessed := PinsProcessed + 1;
                            finally
                                PinProps.Free;
                            end;
                        end;
                        
                        Pad := GrpIter.NextPCBObject;
                    end;
                    
                    // Clean up iterator
                    Component.GroupIterator_Destroy(GrpIter);
                    
                    // Add pins array to component
                    CompProps.Add(BuildJSONArray(PinsArray, 'pins', 1));
                    
                    // Add to components array
                    ComponentsArray.Add(BuildJSONObject(CompProps, 1));
                finally
                    CompProps.Free;
                    PinsArray.Free;
                end;
            end
            else
            begin
                // Component not found, add empty component
                CompProps := TStringList.Create;
                try
                    AddJSONProperty(CompProps, 'designator', Designator);
                    CompProps.Add('"pins": []');
                    
                    // Add to components array
                    ComponentsArray.Add(BuildJSONObject(CompProps, 1));
                finally
                    CompProps.Free;
                end;
            end;
        end;
        
        // Build the final JSON array
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONArray(ComponentsArray);
            Result := WriteJSONToFile(OutputLines, ROOT_DIR+'\temp_pins_data.json');
        finally
            OutputLines.Free;
        end;
    finally
        ComponentsArray.Free;
    end;
end;

// Set absolute position of a single component
function SetComponentPosition(Designator: String; NewX, NewY: Float; Rotation: Float): String;
var
    Board: IPCB_Board;
    Component: IPCB_Component;
    ResultProps: TStringList;
    xorigin, yorigin: TCoord;
begin
    Board := GetBoardSafe(0);
    if (Board = nil) then
    begin
        Result := '{"success": false, "error": "No PCB document is currently active"}';
        Exit;
    end;
    
    Component := Board.GetPcbComponentByRefDes(Designator);
    if (Component = nil) then
    begin
        Result := '{"success": false, "error": "Component not found: ' + Designator + '"}';
        Exit;
    end;
    
    // Get board origin
    xorigin := Board.XOrigin;
    yorigin := Board.YOrigin;
    
    ResultProps := TStringList.Create;
    try
        PCBServer.PreProcess;
        PCBServer.SendMessageToRobots(Component.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);
        
        // Set absolute position using MoveToXY
        // Add origin back since input coordinates are relative to origin
        Component.MoveToXY(MilsToCoord(NewX) + xorigin, MilsToCoord(NewY) + yorigin);
        
        // Set rotation if specified (use -1 to keep current)
        if (Rotation >= 0) then
            Component.Rotation := Rotation;
        
        PCBServer.SendMessageToRobots(Component.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);
        PCBServer.PostProcess;
        
        Client.SendMessage('PCB:Zoom', 'Action=Redraw', 255, Client.CurrentView);
        
        AddJSONProperty(ResultProps, 'designator', Designator);
        AddJSONProperty(ResultProps, 'new_x', FloatToStr(NewX), False);
        AddJSONProperty(ResultProps, 'new_y', FloatToStr(NewY), False);
        AddJSONProperty(ResultProps, 'rotation', FloatToStr(Component.Rotation), False);
        
        Result := '{"success": true, "result": ' + BuildJSONObject(ResultProps) + '}';
    finally
        ResultProps.Free;
    end;
end;

// Create a PCB footprint (SMD pads + silkscreen + courtyard) in the active PcbLib
function CreatePCBFootprint(FootprintName: String; Description: String; PadsList: TStringList; CourtyardXMM: Double; CourtyardYMM: Double): String;
var
    PcbLib      : IPCB_Library;
    LibComp     : IPCB_Component;
    Pad         : IPCB_Pad;
    Track       : IPCB_Track;
    ResultProps : TStringList;
    OutputLines : TStringList;
    i, j        : Integer;
    PadData     : String;
    PadNum      : String;
    XMM, YMM    : Double;
    WMM, HMM    : Double;
    ShapeStr    : String;
    PadShape    : TShape;
    PadCount    : Integer;
    MaxX, MaxY  : Double;
    MinX, MinY  : Double;
    CrtX1, CrtY1, CrtX2, CrtY2 : Double;
    TrackWidth  : TCoord;
    FieldStart  : Integer;
    Fields      : TStringList;
    SilkLayer   : TLayer;
begin
    PcbLib := GetPcbLibSafe(0);
    if PcbLib = nil then
    begin
        Result := '{"success": false, "error": "No PCB library document is currently active. Open a .PcbLib file first."}';
        Exit;
    end;

    ResultProps := TStringList.Create;
    Fields := TStringList.Create;
    PadCount := 0;
    MaxX := -1e9; MaxY := -1e9;
    MinX :=  1e9; MinY :=  1e9;
    SilkLayer := String2Layer('Top Overlay');

    try
        LibComp := PCBServer.CreatePCBLibComp;
        LibComp.Name := FootprintName;

        PcbLib.RegisterComponent(LibComp);

        for i := 0 to PadsList.Count - 1 do
        begin
            PadData := Trim(PadsList[i]);
            if (PadData = '') then continue;

            // Parse pipe-delimited fields manually
            Fields.Clear;
            FieldStart := 1;
            for j := 1 to Length(PadData) + 1 do
            begin
                if (j > Length(PadData)) or (PadData[j] = '|') then
                begin
                    Fields.Add(Trim(Copy(PadData, FieldStart, j - FieldStart)));
                    FieldStart := j + 1;
                end;
            end;

            if Fields.Count < 5 then continue;

            PadNum := Fields[0];
            XMM := SafeStrToFloat(Fields[1]);
            YMM := SafeStrToFloat(Fields[2]);
            WMM := SafeStrToFloat(Fields[3]);
            HMM := SafeStrToFloat(Fields[4]);

            if Fields.Count >= 6 then
                ShapeStr := Fields[5]
            else
                ShapeStr := 'Rect';

            if ShapeStr = 'Round' then
                PadShape := eRounded
            else if ShapeStr = 'Oval' then
                PadShape := eRoundedRectangle
            else
                PadShape := eRectangular;

            Pad := PCBServer.PCBObjectFactory(ePadObject, eNoDimension, eCreate_Default);
            Pad.Name := PadNum;
            Pad.Mode := ePadMode_Simple;
            Pad.HoleSize := 0;
            Pad.x := MMsToCoord(XMM);
            Pad.y := MMsToCoord(YMM);
            Pad.Layer := eTopLayer;
            Pad.TopXSize := MMsToCoord(WMM);
            Pad.TopYSize := MMsToCoord(HMM);
            Pad.TopShape := PadShape;

            LibComp.AddPCBObject(Pad);
            PCBServer.SendMessageToRobots(Pad.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);

            if (XMM - WMM/2) < MinX then MinX := XMM - WMM/2;
            if (YMM - HMM/2) < MinY then MinY := YMM - HMM/2;
            if (XMM + WMM/2) > MaxX then MaxX := XMM + WMM/2;
            if (YMM + HMM/2) > MaxY then MaxY := YMM + HMM/2;

            PadCount := PadCount + 1;
        end;

        // Compute courtyard extents
        if (CourtyardXMM > 0) and (CourtyardYMM > 0) then
        begin
            CrtX1 := -CourtyardXMM; CrtX2 :=  CourtyardXMM;
            CrtY1 := -CourtyardYMM; CrtY2 :=  CourtyardYMM;
        end
        else
        begin
            CrtX1 := MinX - 0.25; CrtX2 := MaxX + 0.25;
            CrtY1 := MinY - 0.25; CrtY2 := MaxY + 0.25;
        end;

        TrackWidth := MMsToCoord(0.1);

        // Courtyard on Mechanical 15
        Track := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
        Track.Layer := ILayer.MechanicalLayer(15);
        Track.x1 := MMsToCoord(CrtX1); Track.y1 := MMsToCoord(CrtY1);
        Track.x2 := MMsToCoord(CrtX2); Track.y2 := MMsToCoord(CrtY1);
        Track.Width := TrackWidth;
        LibComp.AddPCBObject(Track);
        PCBServer.SendMessageToRobots(Track.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);

        Track := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
        Track.Layer := ILayer.MechanicalLayer(15);
        Track.x1 := MMsToCoord(CrtX1); Track.y1 := MMsToCoord(CrtY2);
        Track.x2 := MMsToCoord(CrtX2); Track.y2 := MMsToCoord(CrtY2);
        Track.Width := TrackWidth;
        LibComp.AddPCBObject(Track);
        PCBServer.SendMessageToRobots(Track.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);

        Track := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
        Track.Layer := ILayer.MechanicalLayer(15);
        Track.x1 := MMsToCoord(CrtX1); Track.y1 := MMsToCoord(CrtY1);
        Track.x2 := MMsToCoord(CrtX1); Track.y2 := MMsToCoord(CrtY2);
        Track.Width := TrackWidth;
        LibComp.AddPCBObject(Track);
        PCBServer.SendMessageToRobots(Track.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);

        Track := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
        Track.Layer := ILayer.MechanicalLayer(15);
        Track.x1 := MMsToCoord(CrtX2); Track.y1 := MMsToCoord(CrtY1);
        Track.x2 := MMsToCoord(CrtX2); Track.y2 := MMsToCoord(CrtY2);
        Track.Width := TrackWidth;
        LibComp.AddPCBObject(Track);
        PCBServer.SendMessageToRobots(Track.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);

        // Silkscreen on TopOverlay (inset 0.1mm from courtyard)
        Track := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
        Track.Layer := SilkLayer;
        Track.x1 := MMsToCoord(CrtX1+0.1); Track.y1 := MMsToCoord(CrtY1+0.1);
        Track.x2 := MMsToCoord(CrtX2-0.1); Track.y2 := MMsToCoord(CrtY1+0.1);
        Track.Width := TrackWidth;
        LibComp.AddPCBObject(Track);
        PCBServer.SendMessageToRobots(Track.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);

        Track := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
        Track.Layer := SilkLayer;
        Track.x1 := MMsToCoord(CrtX1+0.1); Track.y1 := MMsToCoord(CrtY2-0.1);
        Track.x2 := MMsToCoord(CrtX2-0.1); Track.y2 := MMsToCoord(CrtY2-0.1);
        Track.Width := TrackWidth;
        LibComp.AddPCBObject(Track);
        PCBServer.SendMessageToRobots(Track.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);

        // Left silk — split to mark pin 1 (gap at top-left corner for pin 1 indicator)
        Track := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
        Track.Layer := SilkLayer;
        Track.x1 := MMsToCoord(CrtX1+0.1); Track.y1 := MMsToCoord(CrtY1+0.1);
        Track.x2 := MMsToCoord(CrtX1+0.1); Track.y2 := MMsToCoord(CrtY2-0.6);
        Track.Width := TrackWidth;
        LibComp.AddPCBObject(Track);
        PCBServer.SendMessageToRobots(Track.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);

        // Right silk
        Track := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
        Track.Layer := SilkLayer;
        Track.x1 := MMsToCoord(CrtX2-0.1); Track.y1 := MMsToCoord(CrtY1+0.1);
        Track.x2 := MMsToCoord(CrtX2-0.1); Track.y2 := MMsToCoord(CrtY2-0.1);
        Track.Width := TrackWidth;
        LibComp.AddPCBObject(Track);
        PCBServer.SendMessageToRobots(Track.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, c_NoEventData);

        // Register with library board, navigate, and refresh
        PCBServer.SendMessageToRobots(PcbLib.Board.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, LibComp.I_ObjectAddress);
        PcbLib.CurrentComponent := LibComp;
        PcbLib.Board.ViewManager_FullUpdate;

        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'footprint_name', FootprintName);
        AddJSONInteger(ResultProps, 'pad_count', PadCount);
        AddJSONNumber(ResultProps, 'courtyard_width_mm', CrtX2 - CrtX1);
        AddJSONNumber(ResultProps, 'courtyard_height_mm', CrtY2 - CrtY1);

        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
        Fields.Free;
    end;
end;

// Function to move components by X and Y offsets and set rotation
function MoveComponentsByDesignators(DesignatorsList: TStringList; XOffset, YOffset: TCoord; Rotation: TAngle): String;
var
    Board          : IPCB_Board;
    Component      : IPCB_Component;
    ResultProps    : TStringList;
    MissingArray   : TStringList;
    Designator     : String;
    i              : Integer;
    MovedCount     : Integer;
    OutputLines    : TStringList;
begin
    // Retrieve the current board
    Board := GetBoardSafe(0);
    if (Board = nil) then
    begin
        Result := 'ERROR: No PCB document is currently active';
        Exit;
    end;
    
    // Create output properties
    ResultProps := TStringList.Create;
    MissingArray := TStringList.Create;
    MovedCount := 0;
    
    try
        // Start transaction
        PCBServer.PreProcess;
        
        // Process each designator
        for i := 0 to DesignatorsList.Count - 1 do
        begin
            Designator := Trim(DesignatorsList[i]);
            
            // Use direct function to get component by designator
            Component := Board.GetPcbComponentByRefDes(Designator);
            
            if (Component <> Nil) then
            begin
                // Begin modify
                PCBServer.SendMessageToRobots(Component.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);
                
                // Move the component by the specified offsets
                Component.MoveByXY(XOffset, YOffset);
                
                // Set rotation if specified (non-zero)
                if (Rotation <> 0) then
                    Component.Rotation := Rotation;
                
                // End modify
                PCBServer.SendMessageToRobots(Component.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);
                
                MovedCount := MovedCount + 1;
            end
            else
            begin
                // Add to missing designators list
                MissingArray.Add('"' + JSONEscapeString(Designator) + '"');
            end;
        end;
        
        // End transaction
        PCBServer.PostProcess;
        
        // Update PCB document
        Client.SendMessage('PCB:Zoom', 'Action=Redraw', 255, Client.CurrentView);
        
        // Create result JSON
        AddJSONInteger(ResultProps, 'moved_count', MovedCount);
        
        // Add missing designators array
        if (MissingArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(MissingArray, 'missing_designators'))
        else
            ResultProps.Add('"missing_designators": []');
        
        // Build final JSON
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
        MissingArray.Free;
    end;
end;

// Minimum primitive-to-primitive distance between two components in mils,
// ignoring text primitives (designator/comment strings float over neighbors
// and would poison the measurement). 0 = touching or overlapping.
function ComponentMinDistance(Board: IPCB_Board; CompA, CompB: IPCB_Component): Double;
var
    ItA, ItB : IPCB_GroupIterator;
    PA, PB   : IPCB_Primitive;
    D, MinD  : Integer;
begin
    MinD := 2147483647;

    ItA := CompA.GroupIterator_Create;
    ItA.SetState_FilterAll;
    PA := ItA.FirstPCBObject;
    while (PA <> nil) do
    begin
        if (PA.ObjectId <> eTextObject) then
        begin
            ItB := CompB.GroupIterator_Create;
            ItB.SetState_FilterAll;
            PB := ItB.FirstPCBObject;
            while (PB <> nil) do
            begin
                if (PB.ObjectId <> eTextObject) then
                begin
                    D := Board.PrimPrimDistance(PA, PB);
                    if (D < MinD) then MinD := D;
                end;

                // Early exit once touching - it cannot get closer
                if (MinD = 0) then
                    PB := nil
                else
                    PB := ItB.NextPCBObject;
            end;
            CompB.GroupIterator_Destroy(ItB);
        end;

        if (MinD = 0) then
            PA := nil
        else
            PA := ItA.NextPCBObject;
    end;
    CompA.GroupIterator_Destroy(ItA);

    Result := CoordToMils(MinD);
end;

// Check component placement for overlaps and clearance violations.
// Targets are the given designators (or the current selection when the list
// is empty); each target is checked against every other component on the same
// side of the board. Bounding boxes act as a fast prefilter; close pairs are
// measured precisely with Board.PrimPrimDistance (minimum distance between
// any two primitives of the components, 0 = touching/overlapping).
function CheckPlacement(DesignatorsList: TStringList; ClearanceMils: Double): String;
var
    Board           : IPCB_Board;
    Iterator        : IPCB_BoardIterator;
    Target, Other   : IPCB_Component;
    Targets         : TStringList;
    Processed       : TStringList;
    MissingArray    : TStringList;
    ViolationsArray : TStringList;
    VProps          : TStringList;
    ResultProps     : TStringList;
    RectA, RectB    : TCoordRect;
    Designator      : String;
    i               : Integer;
    OverlapX, OverlapY : Double;
    Separation      : Double;
    DistMils        : Double;
    PairsChecked    : Integer;
    IsOverlap       : Boolean;
begin
    Board := GetBoardSafe(0);
    if (Board = nil) then
    begin
        Result := 'ERROR: No PCB document is currently active';
        Exit;
    end;

    if (ClearanceMils <= 0) then
        ClearanceMils := 6;

    Targets := TStringList.Create;
    Processed := TStringList.Create;
    MissingArray := TStringList.Create;
    ViolationsArray := TStringList.Create;
    ResultProps := TStringList.Create;
    PairsChecked := 0;

    try
        // Build the target list: explicit designators, or current selection
        if (DesignatorsList.Count > 0) then
        begin
            for i := 0 to DesignatorsList.Count - 1 do
            begin
                Designator := Trim(DesignatorsList[i]);
                if (Board.GetPcbComponentByRefDes(Designator) <> nil) then
                    Targets.Add(Designator)
                else
                    MissingArray.Add('"' + JSONEscapeString(Designator) + '"');
            end;
        end
        else
        begin
            for i := 0 to Board.SelectecObjectCount - 1 do
                if (Board.SelectecObject[i].ObjectId = eComponentObject) then
                    Targets.Add(Board.SelectecObject[i].Name.Text);
        end;

        if (Targets.Count = 0) then
        begin
            Result := 'ERROR: No components to check (no designators given and no components selected)';
            Exit;
        end;

        // Check each target against every other component on the same side
        for i := 0 to Targets.Count - 1 do
        begin
            Target := Board.GetPcbComponentByRefDes(Targets[i]);
            RectA := Target.BoundingRectangleNoNameComment;

            Iterator := Board.BoardIterator_Create;
            Iterator.AddFilter_ObjectSet(MkSet(eComponentObject));
            Iterator.AddFilter_IPCB_LayerSet(LayerSet.AllLayers);
            Iterator.AddFilter_Method(eProcessAll);

            Other := Iterator.FirstPCBObject;
            while (Other <> nil) do
            begin
                if (Other.Name.Text <> Target.Name.Text) and
                   (Other.Layer = Target.Layer) and
                   (Processed.IndexOf(Other.Name.Text) < 0) then
                begin
                    RectB := Other.BoundingRectangleNoNameComment;

                    // Bounding-box overlap/separation in mils (negative = gap)
                    OverlapX := CoordToMils(Min(RectA.Right, RectB.Right) - Max(RectA.Left, RectB.Left));
                    OverlapY := CoordToMils(Min(RectA.Top, RectB.Top) - Max(RectA.Bottom, RectB.Bottom));

                    if (OverlapX > 0) and (OverlapY > 0) then
                        Separation := 0
                    else
                        Separation := Max(-OverlapX, -OverlapY);

                    // Only measure precisely when the prefilter says "close"
                    if (Separation < ClearanceMils + 25) then
                    begin
                        PairsChecked := PairsChecked + 1;
                        DistMils := ComponentMinDistance(Board, Target, Other);
                        IsOverlap := (OverlapX > 0) and (OverlapY > 0);

                        if (IsOverlap) or (DistMils < ClearanceMils) then
                        begin
                            VProps := TStringList.Create;
                            try
                                AddJSONProperty(VProps, 'a', Target.Name.Text);
                                AddJSONProperty(VProps, 'b', Other.Name.Text);
                                AddJSONProperty(VProps, 'layer', Layer2String(Target.Layer));
                                if IsOverlap then
                                    AddJSONProperty(VProps, 'type', 'bounding_box_overlap')
                                else
                                    AddJSONProperty(VProps, 'type', 'clearance');
                                AddJSONNumber(VProps, 'distance_mils', Round(DistMils * 100) / 100);
                                if IsOverlap then
                                begin
                                    AddJSONNumber(VProps, 'overlap_x_mils', Round(OverlapX * 100) / 100);
                                    AddJSONNumber(VProps, 'overlap_y_mils', Round(OverlapY * 100) / 100);
                                end;
                                AddJSONNumber(VProps, 'b_x', CoordToMils(Other.x - Board.XOrigin));
                                AddJSONNumber(VProps, 'b_y', CoordToMils(Other.y - Board.YOrigin));
                                ViolationsArray.Add(BuildJSONObject(VProps, 2));
                            finally
                                VProps.Free;
                            end;
                        end;
                    end;
                end;

                Other := Iterator.NextPCBObject;
            end;

            Board.BoardIterator_Destroy(Iterator);
            Processed.Add(Target.Name.Text);
        end;

        AddJSONInteger(ResultProps, 'checked_count', Targets.Count);
        AddJSONNumber(ResultProps, 'clearance_mils', ClearanceMils);
        AddJSONInteger(ResultProps, 'close_pairs_measured', PairsChecked);
        AddJSONInteger(ResultProps, 'violation_count', ViolationsArray.Count);

        if (MissingArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(MissingArray, 'missing_designators'))
        else
            ResultProps.Add('"missing_designators": []');

        if (ViolationsArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(ViolationsArray, 'violations', 1))
        else
            ResultProps.Add('"violations": []');

        Result := BuildJSONObject(ResultProps);
    finally
        Targets.Free;
        Processed.Free;
        MissingArray.Free;
        ViolationsArray.Free;
        ResultProps.Free;
    end;
end;

// Get all pads on every net touched by the given components (or the current
// selection when the list is empty). Returns a flat board-wide pad list -
// including pads of components outside the target set - so the caller can
// group by net and compute airline lengths. Coordinates in mils relative to
// the board origin.
function GetNetConnections(ROOT_DIR: String; DesignatorsList: TStringList): String;
var
    Board       : IPCB_Board;
    Component   : IPCB_Component;
    Iterator    : IPCB_BoardIterator;
    GrpIter     : IPCB_GroupIterator;
    Pad         : IPCB_Pad;
    NetNames    : TStringList;
    TargetNames : TStringList;
    PadsArray   : TStringList;
    PadProps    : TStringList;
    ResultProps : TStringList;
    NamesArray  : TStringList;
    OutputLines : TStringList;
    Designator  : String;
    xorigin, yorigin : Integer;
    i           : Integer;
begin
    Board := GetBoardSafe(0);
    if (Board = nil) then
    begin
        Result := 'ERROR: No PCB document is currently active';
        Exit;
    end;

    xorigin := Board.XOrigin;
    yorigin := Board.YOrigin;

    NetNames := TStringList.Create;
    TargetNames := TStringList.Create;
    PadsArray := TStringList.Create;
    ResultProps := TStringList.Create;
    NamesArray := TStringList.Create;

    try
        // Build the target component list: explicit designators, or selection
        if (DesignatorsList.Count > 0) then
        begin
            for i := 0 to DesignatorsList.Count - 1 do
            begin
                Designator := Trim(DesignatorsList[i]);
                if (Board.GetPcbComponentByRefDes(Designator) <> nil) then
                    TargetNames.Add(Designator);
            end;
        end
        else
        begin
            for i := 0 to Board.SelectecObjectCount - 1 do
                if (Board.SelectecObject[i].ObjectId = eComponentObject) then
                    TargetNames.Add(Board.SelectecObject[i].Name.Text);
        end;

        if (TargetNames.Count = 0) then
        begin
            Result := 'ERROR: No components found (no designators given and no components selected)';
            Exit;
        end;

        // Collect the set of nets touched by the target components
        for i := 0 to TargetNames.Count - 1 do
        begin
            Component := Board.GetPcbComponentByRefDes(TargetNames[i]);
            GrpIter := Component.GroupIterator_Create;
            GrpIter.SetState_FilterAll;
            GrpIter.AddFilter_ObjectSet(MkSet(ePadObject));

            Pad := GrpIter.FirstPCBObject;
            while (Pad <> nil) do
            begin
                if (Pad.Net <> nil) then
                    if (NetNames.IndexOf(Pad.Net.Name) < 0) then
                        NetNames.Add(Pad.Net.Name);
                Pad := GrpIter.NextPCBObject;
            end;

            Component.GroupIterator_Destroy(GrpIter);
        end;

        // One board-wide pass: emit every pad on any of those nets
        Iterator := Board.BoardIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(ePadObject));
        Iterator.AddFilter_IPCB_LayerSet(LayerSet.AllLayers);
        Iterator.AddFilter_Method(eProcessAll);

        Pad := Iterator.FirstPCBObject;
        while (Pad <> nil) do
        begin
            if (Pad.Net <> nil) then
            begin
                if (NetNames.IndexOf(Pad.Net.Name) >= 0) then
                begin
                    PadProps := TStringList.Create;
                    try
                        AddJSONProperty(PadProps, 'net', Pad.Net.Name);
                        if (Pad.Component <> nil) then
                            AddJSONProperty(PadProps, 'designator', Pad.Component.Name.Text)
                        else
                            AddJSONProperty(PadProps, 'designator', '');
                        AddJSONProperty(PadProps, 'pin', Pad.Name);
                        AddJSONNumber(PadProps, 'x', CoordToMils(Pad.x - xorigin));
                        AddJSONNumber(PadProps, 'y', CoordToMils(Pad.y - yorigin));
                        PadsArray.Add(BuildJSONObject(PadProps, 2));
                    finally
                        PadProps.Free;
                    end;
                end;
            end;
            Pad := Iterator.NextPCBObject;
        end;

        Board.BoardIterator_Destroy(Iterator);

        // Build the result - include the resolved targets so the caller
        // knows which components were analyzed when using the selection
        for i := 0 to TargetNames.Count - 1 do
            NamesArray.Add('"' + JSONEscapeString(TargetNames[i]) + '"');
        ResultProps.Add(BuildJSONArray(NamesArray, 'targets'));
        NamesArray.Clear;

        for i := 0 to NetNames.Count - 1 do
            NamesArray.Add('"' + JSONEscapeString(NetNames[i]) + '"');

        if (NamesArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(NamesArray, 'net_names'))
        else
            ResultProps.Add('"net_names": []');

        if (PadsArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(PadsArray, 'pads', 1))
        else
            ResultProps.Add('"pads": []');

        // Potentially large (plane nets) - go through the temp-file path
        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := WriteJSONToFile(OutputLines, ROOT_DIR+'\temp_net_connections.json');
        finally
            OutputLines.Free;
        end;
    finally
        NetNames.Free;
        TargetNames.Free;
        PadsArray.Free;
        ResultProps.Free;
        NamesArray.Free;
    end;
end;

// Place multiple components at absolute positions in a single transaction.
// Each entry in PlacementsList is 'Designator|X|Y|Rotation|Layer' where X/Y
// are mils relative to the board origin, Rotation is degrees CCW (-1 = keep
// current) and Layer is 'top', 'bottom' or '' (keep current side).
function PlaceComponentsFromList(PlacementsList: TStringList): String;
var
    Board            : IPCB_Board;
    Component        : IPCB_Component;
    ResultProps      : TStringList;
    MissingArray     : TStringList;
    PlacedArray      : TStringList;
    CompProps        : TStringList;
    Entry            : String;
    Designator       : String;
    FieldValue       : String;
    LayerStr         : String;
    NewX, NewY       : Double;
    Rotation         : Double;
    xorigin, yorigin : TCoord;
    i                : Integer;
    PlacedCount      : Integer;
begin
    Board := GetBoardSafe(0);
    if (Board = nil) then
    begin
        Result := 'ERROR: No PCB document is currently active';
        Exit;
    end;

    xorigin := Board.XOrigin;
    yorigin := Board.YOrigin;

    ResultProps := TStringList.Create;
    MissingArray := TStringList.Create;
    PlacedArray := TStringList.Create;
    PlacedCount := 0;

    try
        // Single transaction for the whole batch (one undo step)
        PCBServer.PreProcess;

        for i := 0 to PlacementsList.Count - 1 do
        begin
            Entry := Trim(PlacementsList[i]);
            if (Entry <> '') then
            begin
                Designator := Trim(GetFieldFromPipeString(Entry, 0));
                NewX := SafeStrToFloat(GetFieldFromPipeString(Entry, 1));
                NewY := SafeStrToFloat(GetFieldFromPipeString(Entry, 2));

                // Rotation is optional: missing/empty field means keep current
                FieldValue := Trim(GetFieldFromPipeString(Entry, 3));
                if (FieldValue <> '') then
                    Rotation := SafeStrToFloat(FieldValue)
                else
                    Rotation := -1;

                LayerStr := LowerCase(Trim(GetFieldFromPipeString(Entry, 4)));

                Component := Board.GetPcbComponentByRefDes(Designator);

                if (Component <> nil) then
                begin
                    PCBServer.SendMessageToRobots(Component.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);

                    // Change layer first: flipping mirrors the footprint, so
                    // position and rotation are applied afterwards to keep the
                    // requested values authoritative
                    if (LayerStr = 'top') and (Component.Layer = eBottomLayer) then
                        Component.Layer := eTopLayer
                    else if (LayerStr = 'bottom') and (Component.Layer = eTopLayer) then
                        Component.Layer := eBottomLayer;

                    Component.MoveToXY(MilsToCoord(NewX) + xorigin, MilsToCoord(NewY) + yorigin);

                    if (Rotation >= 0) then
                        Component.Rotation := Rotation;

                    PCBServer.SendMessageToRobots(Component.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);

                    // Report the final state as Altium sees it
                    CompProps := TStringList.Create;
                    try
                        AddJSONProperty(CompProps, 'designator', Component.Name.Text);
                        AddJSONNumber(CompProps, 'x', CoordToMils(Component.x - xorigin));
                        AddJSONNumber(CompProps, 'y', CoordToMils(Component.y - yorigin));
                        AddJSONNumber(CompProps, 'rotation', Component.Rotation);
                        AddJSONProperty(CompProps, 'layer', Layer2String(Component.Layer));
                        PlacedArray.Add(BuildJSONObject(CompProps, 2));
                    finally
                        CompProps.Free;
                    end;

                    PlacedCount := PlacedCount + 1;
                end
                else
                begin
                    MissingArray.Add('"' + JSONEscapeString(Designator) + '"');
                end;
            end;
        end;

        PCBServer.PostProcess;

        // Update PCB document
        Client.SendMessage('PCB:Zoom', 'Action=Redraw', 255, Client.CurrentView);

        AddJSONInteger(ResultProps, 'placed_count', PlacedCount);

        if (MissingArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(MissingArray, 'missing_designators'))
        else
            ResultProps.Add('"missing_designators": []');

        if (PlacedArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(PlacedArray, 'components', 1))
        else
            ResultProps.Add('"components": []');

        Result := BuildJSONObject(ResultProps);
    finally
        ResultProps.Free;
        MissingArray.Free;
        PlacedArray.Free;
    end;
end;

// Read-only diagnostic: reports the primitive composition and overall bounding
// box (in mm) of whichever footprint is currently open/focused in the active
// PCB library document. Used to plan a scale operation before touching geometry.
function GetCurrentPCBLibFootprintInfo(ROOT_DIR): String;
var
    PcbLib      : IPCB_Library;
    LibComp     : IPCB_LibComponent;
    LibBoard    : IPCB_Board;
    Iterator    : IPCB_BoardIterator;
    Prim        : IPCB_Primitive;
    Rect        : TCoordRect;
    HasAny      : Boolean;
    MinX, MinY, MaxX, MaxY : TCoord;
    NTrack, NArc, NRegion, NFill, NText, NPad, NVia, NBody, NOther : Integer;
    ResultProps : TStringList;
    OutputLines : TStringList;
begin
    PcbLib := PCBServer.GetCurrentPCBLibrary;
    if PcbLib = nil then
    begin
        Result := '{"success": false, "error": "No PCB library document is currently active. Open a .PcbLib file first."}';
        Exit;
    end;

    LibComp := PcbLib.GetState_CurrentComponent;
    if LibComp = nil then
    begin
        Result := '{"success": false, "error": "No footprint is currently open/selected in the PCB library editor."}';
        Exit;
    end;

    LibBoard := PcbLib.GetState_Board;
    if LibBoard = nil then
    begin
        Result := '{"success": false, "error": "Could not get the PCB library editor board for the current footprint."}';
        Exit;
    end;

    NTrack := 0; NArc := 0; NRegion := 0; NFill := 0; NText := 0; NPad := 0; NVia := 0; NBody := 0; NOther := 0;
    HasAny := False;
    MinX := 0; MinY := 0; MaxX := 0; MaxY := 0;

    ResultProps := TStringList.Create;
    try
        Iterator := LibBoard.BoardIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(eTrackObject, eArcObject, eRegionObject, eFillObject, eTextObject, ePadObject, eViaObject, eComponentBodyObject));
        Iterator.AddFilter_LayerSet(AllLayers);
        Iterator.AddFilter_Method(eProcessAll);

        Prim := Iterator.FirstPCBObject;
        while (Prim <> nil) do
        begin
            case Prim.ObjectId of
                eTrackObject:          NTrack  := NTrack  + 1;
                eArcObject:            NArc    := NArc    + 1;
                eRegionObject:         NRegion := NRegion + 1;
                eFillObject:           NFill   := NFill   + 1;
                eTextObject:           NText   := NText   + 1;
                ePadObject:            NPad    := NPad    + 1;
                eViaObject:            NVia    := NVia    + 1;
                eComponentBodyObject:  NBody   := NBody   + 1;
            else
                NOther := NOther + 1;
            end;

            Rect := Prim.BoundingRectangle;
            if not HasAny then
            begin
                MinX := Rect.Left;   MaxX := Rect.Right;
                MinY := Rect.Bottom; MaxY := Rect.Top;
                HasAny := True;
            end
            else
            begin
                if Rect.Left   < MinX then MinX := Rect.Left;
                if Rect.Right  > MaxX then MaxX := Rect.Right;
                if Rect.Bottom < MinY then MinY := Rect.Bottom;
                if Rect.Top    > MaxY then MaxY := Rect.Top;
            end;

            Prim := Iterator.NextPCBObject;
        end;
        LibBoard.BoardIterator_Destroy(Iterator);

        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'footprint_name', LibComp.Name);
        AddJSONInteger(ResultProps, 'track_count', NTrack);
        AddJSONInteger(ResultProps, 'arc_count', NArc);
        AddJSONInteger(ResultProps, 'region_count', NRegion);
        AddJSONInteger(ResultProps, 'fill_count', NFill);
        AddJSONInteger(ResultProps, 'text_count', NText);
        AddJSONInteger(ResultProps, 'pad_count', NPad);
        AddJSONInteger(ResultProps, 'via_count', NVia);
        AddJSONInteger(ResultProps, 'component_body_count', NBody);
        AddJSONInteger(ResultProps, 'other_count', NOther);
        if HasAny then
        begin
            AddJSONNumber(ResultProps, 'bbox_min_x_mm', CoordToMMs(MinX));
            AddJSONNumber(ResultProps, 'bbox_min_y_mm', CoordToMMs(MinY));
            AddJSONNumber(ResultProps, 'bbox_max_x_mm', CoordToMMs(MaxX));
            AddJSONNumber(ResultProps, 'bbox_max_y_mm', CoordToMMs(MaxY));
            AddJSONNumber(ResultProps, 'bbox_width_mm', CoordToMMs(MaxX - MinX));
            AddJSONNumber(ResultProps, 'bbox_height_mm', CoordToMMs(MaxY - MinY));
        end
        else
        begin
            AddJSONBoolean(ResultProps, 'empty', True);
        end;

        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;

// Uniformly scales every primitive of the currently open/focused PcbLib
// footprint by ScaleFactor around the CENTER of its current bounding box (not
// the origin) so the artwork shrinks/grows in place instead of also jumping
// toward (0,0) - the footprint's reference point is not necessarily anywhere
// near its geometry (e.g. duplicated/imported logos are often offset far from
// origin). Handles Track, Arc, Region (silkscreen/logo artwork outlines), Pad,
// Via and Text. Fill and ComponentBody primitives are left untouched and
// counted separately (report them so the caller can decide whether to handle
// them manually in the GUI).
function ScaleCurrentPCBLibFootprint(ScaleFactor: Double): String;
var
    PcbLib      : IPCB_Library;
    LibComp     : IPCB_LibComponent;
    LibBoard    : IPCB_Board;
    Iterator    : IPCB_BoardIterator;
    Prim        : IPCB_Primitive;
    Track       : IPCB_Track;
    Arc         : IPCB_Arc;
    Region      : IPCB_Region;
    TextObj     : IPCB_Text;
    Pad         : IPCB_Pad;
    Via         : IPCB_Via;
    Contour     : IPCB_Contour;
    i           : Integer;
    Rect        : TCoordRect;
    HasAny      : Boolean;
    MinX, MinY, MaxX, MaxY : TCoord;
    CenterX, CenterY : TCoord;
    NScaled, NSkipped : Integer;
    ResultProps : TStringList;
    OutputLines : TStringList;
begin
    if (ScaleFactor <= 0) then
    begin
        Result := '{"success": false, "error": "scale_factor must be greater than 0"}';
        Exit;
    end;

    PcbLib := PCBServer.GetCurrentPCBLibrary;
    if PcbLib = nil then
    begin
        Result := '{"success": false, "error": "No PCB library document is currently active. Open a .PcbLib file first."}';
        Exit;
    end;

    LibComp := PcbLib.GetState_CurrentComponent;
    if LibComp = nil then
    begin
        Result := '{"success": false, "error": "No footprint is currently open/selected in the PCB library editor."}';
        Exit;
    end;

    LibBoard := PcbLib.GetState_Board;
    if LibBoard = nil then
    begin
        Result := '{"success": false, "error": "Could not get the PCB library editor board for the current footprint."}';
        Exit;
    end;

    NScaled := 0;
    NSkipped := 0;

    ResultProps := TStringList.Create;
    try
        // First pass: measure the current bounding box so we can scale around
        // its center rather than the origin.
        HasAny := False;
        MinX := 0; MinY := 0; MaxX := 0; MaxY := 0;

        Iterator := LibBoard.BoardIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(eTrackObject, eArcObject, eRegionObject, eFillObject, eTextObject, ePadObject, eViaObject, eComponentBodyObject));
        Iterator.AddFilter_LayerSet(AllLayers);
        Iterator.AddFilter_Method(eProcessAll);

        Prim := Iterator.FirstPCBObject;
        while (Prim <> nil) do
        begin
            Rect := Prim.BoundingRectangle;
            if not HasAny then
            begin
                MinX := Rect.Left;   MaxX := Rect.Right;
                MinY := Rect.Bottom; MaxY := Rect.Top;
                HasAny := True;
            end
            else
            begin
                if Rect.Left   < MinX then MinX := Rect.Left;
                if Rect.Right  > MaxX then MaxX := Rect.Right;
                if Rect.Bottom < MinY then MinY := Rect.Bottom;
                if Rect.Top    > MaxY then MaxY := Rect.Top;
            end;
            Prim := Iterator.NextPCBObject;
        end;
        LibBoard.BoardIterator_Destroy(Iterator);

        CenterX := Round((MinX + MaxX) / 2);
        CenterY := Round((MinY + MaxY) / 2);

        PCBServer.PreProcess;
        try
            Iterator := LibBoard.BoardIterator_Create;
            Iterator.AddFilter_ObjectSet(MkSet(eTrackObject, eArcObject, eRegionObject, eFillObject, eTextObject, ePadObject, eViaObject, eComponentBodyObject));
            Iterator.AddFilter_LayerSet(AllLayers);
            Iterator.AddFilter_Method(eProcessAll);

            Prim := Iterator.FirstPCBObject;
            while (Prim <> nil) do
            begin
                case Prim.ObjectId of
                    eTrackObject:
                    begin
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);
                        Track := Prim;
                        Track.X1 := CenterX + Round((Track.X1 - CenterX) * ScaleFactor);
                        Track.Y1 := CenterY + Round((Track.Y1 - CenterY) * ScaleFactor);
                        Track.X2 := CenterX + Round((Track.X2 - CenterX) * ScaleFactor);
                        Track.Y2 := CenterY + Round((Track.Y2 - CenterY) * ScaleFactor);
                        Track.Width := Round(Track.Width * ScaleFactor);
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);
                        NScaled := NScaled + 1;
                    end;

                    eArcObject:
                    begin
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);
                        Arc := Prim;
                        Arc.XCenter := CenterX + Round((Arc.XCenter - CenterX) * ScaleFactor);
                        Arc.YCenter := CenterY + Round((Arc.YCenter - CenterY) * ScaleFactor);
                        Arc.Radius := Round(Arc.Radius * ScaleFactor);
                        Arc.LineWidth := Round(Arc.LineWidth * ScaleFactor);
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);
                        NScaled := NScaled + 1;
                    end;

                    eRegionObject:
                    begin
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);
                        Region := Prim;
                        Contour := Region.MainContour.Replicate;
                        for i := 1 to Contour.Count do
                        begin
                            Contour.X[i] := CenterX + Round((Contour.X[i] - CenterX) * ScaleFactor);
                            Contour.Y[i] := CenterY + Round((Contour.Y[i] - CenterY) * ScaleFactor);
                        end;
                        Region.SetOutlineContour(Contour);
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);
                        NScaled := NScaled + 1;
                    end;

                    ePadObject:
                    begin
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);
                        Pad := Prim;
                        Pad.X := CenterX + Round((Pad.X - CenterX) * ScaleFactor);
                        Pad.Y := CenterY + Round((Pad.Y - CenterY) * ScaleFactor);
                        Pad.TopXSize := Round(Pad.TopXSize * ScaleFactor);
                        Pad.TopYSize := Round(Pad.TopYSize * ScaleFactor);
                        Pad.HoleSize := Round(Pad.HoleSize * ScaleFactor);
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);
                        NScaled := NScaled + 1;
                    end;

                    eViaObject:
                    begin
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);
                        Via := Prim;
                        Via.X := CenterX + Round((Via.X - CenterX) * ScaleFactor);
                        Via.Y := CenterY + Round((Via.Y - CenterY) * ScaleFactor);
                        Via.Size := Round(Via.Size * ScaleFactor);
                        Via.HoleSize := Round(Via.HoleSize * ScaleFactor);
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);
                        NScaled := NScaled + 1;
                    end;

                    eTextObject:
                    begin
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);
                        TextObj := Prim;
                        TextObj.XLocation := CenterX + Round((TextObj.XLocation - CenterX) * ScaleFactor);
                        TextObj.YLocation := CenterY + Round((TextObj.YLocation - CenterY) * ScaleFactor);
                        TextObj.Height := Round(TextObj.Height * ScaleFactor);
                        TextObj.Width := Round(TextObj.Width * ScaleFactor);
                        PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);
                        NScaled := NScaled + 1;
                    end;
                else
                    NSkipped := NSkipped + 1;
                end;

                Prim := Iterator.NextPCBObject;
            end;
            LibBoard.BoardIterator_Destroy(Iterator);
        finally
            PCBServer.PostProcess;
        end;

        LibBoard.ViewManager_FullUpdate;

        // Measure the resulting bounding box for confirmation
        HasAny := False;
        MinX := 0; MinY := 0; MaxX := 0; MaxY := 0;

        Iterator := LibBoard.BoardIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(eTrackObject, eArcObject, eRegionObject, eFillObject, eTextObject, ePadObject, eViaObject, eComponentBodyObject));
        Iterator.AddFilter_LayerSet(AllLayers);
        Iterator.AddFilter_Method(eProcessAll);

        Prim := Iterator.FirstPCBObject;
        while (Prim <> nil) do
        begin
            Rect := Prim.BoundingRectangle;
            if not HasAny then
            begin
                MinX := Rect.Left;   MaxX := Rect.Right;
                MinY := Rect.Bottom; MaxY := Rect.Top;
                HasAny := True;
            end
            else
            begin
                if Rect.Left   < MinX then MinX := Rect.Left;
                if Rect.Right  > MaxX then MaxX := Rect.Right;
                if Rect.Bottom < MinY then MinY := Rect.Bottom;
                if Rect.Top    > MaxY then MaxY := Rect.Top;
            end;
            Prim := Iterator.NextPCBObject;
        end;
        LibBoard.BoardIterator_Destroy(Iterator);

        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'footprint_name', LibComp.Name);
        AddJSONNumber(ResultProps, 'scale_factor', ScaleFactor);
        AddJSONInteger(ResultProps, 'scaled_count', NScaled);
        AddJSONInteger(ResultProps, 'skipped_count', NSkipped);
        if HasAny then
        begin
            AddJSONNumber(ResultProps, 'bbox_width_mm', CoordToMMs(MaxX - MinX));
            AddJSONNumber(ResultProps, 'bbox_height_mm', CoordToMMs(MaxY - MinY));
        end;

        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
    end;
end;

// Read-only: reports the currently-selected Track and Arc primitives on the
// active PCB document, with full geometry in mm, so their exact shape can be
// computed/edited precisely (e.g. offsetting part of a board outline).
function GetSelectedTracksAndArcs(ROOT_DIR): String;
var
    Board       : IPCB_Board;
    Iterator    : IPCB_BoardIterator;
    Prim        : IPCB_Primitive;
    Track       : IPCB_Track;
    Arc         : IPCB_Arc;
    TracksArray : TStringList;
    ArcsArray   : TStringList;
    ItemProps   : TStringList;
    ResultProps : TStringList;
    OutputLines : TStringList;
begin
    Board := PCBServer.GetCurrentPCBBoard;
    if Board = nil then
    begin
        Result := '{"success": false, "error": "No PCB document is currently active"}';
        Exit;
    end;

    TracksArray := TStringList.Create;
    ArcsArray := TStringList.Create;
    ResultProps := TStringList.Create;
    try
        Iterator := Board.BoardIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(eTrackObject, eArcObject));
        Iterator.AddFilter_LayerSet(AllLayers);
        Iterator.AddFilter_Method(eProcessAll);

        Prim := Iterator.FirstPCBObject;
        while (Prim <> nil) do
        begin
            if Prim.Selected then
            begin
                if (Prim.ObjectId = eTrackObject) then
                begin
                    Track := Prim;
                    ItemProps := TStringList.Create;
                    try
                        AddJSONProperty(ItemProps, 'layer', Layer2String(Track.Layer));
                        AddJSONNumber(ItemProps, 'x1_mm', CoordToMMs(Track.X1));
                        AddJSONNumber(ItemProps, 'y1_mm', CoordToMMs(Track.Y1));
                        AddJSONNumber(ItemProps, 'x2_mm', CoordToMMs(Track.X2));
                        AddJSONNumber(ItemProps, 'y2_mm', CoordToMMs(Track.Y2));
                        AddJSONNumber(ItemProps, 'width_mm', CoordToMMs(Track.Width));
                        TracksArray.Add(BuildJSONObject(ItemProps, 2));
                    finally
                        ItemProps.Free;
                    end;
                end
                else if (Prim.ObjectId = eArcObject) then
                begin
                    Arc := Prim;
                    ItemProps := TStringList.Create;
                    try
                        AddJSONProperty(ItemProps, 'layer', Layer2String(Arc.Layer));
                        AddJSONNumber(ItemProps, 'x_center_mm', CoordToMMs(Arc.XCenter));
                        AddJSONNumber(ItemProps, 'y_center_mm', CoordToMMs(Arc.YCenter));
                        AddJSONNumber(ItemProps, 'radius_mm', CoordToMMs(Arc.Radius));
                        AddJSONNumber(ItemProps, 'start_angle_deg', Arc.StartAngle);
                        AddJSONNumber(ItemProps, 'end_angle_deg', Arc.EndAngle);
                        AddJSONNumber(ItemProps, 'line_width_mm', CoordToMMs(Arc.LineWidth));
                        ArcsArray.Add(BuildJSONObject(ItemProps, 2));
                    finally
                        ItemProps.Free;
                    end;
                end;
            end;

            Prim := Iterator.NextPCBObject;
        end;
        Board.BoardIterator_Destroy(Iterator);

        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONInteger(ResultProps, 'track_count', TracksArray.Count);
        AddJSONInteger(ResultProps, 'arc_count', ArcsArray.Count);
        if (TracksArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(TracksArray, 'tracks', 1))
        else
            ResultProps.Add('"tracks": []');
        if (ArcsArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(ArcsArray, 'arcs', 1))
        else
            ResultProps.Add('"arcs": []');

        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
        TracksArray.Free;
        ArcsArray.Free;
    end;
end;

// Precisely edits specific currently-SELECTED Track primitives by exact
// coordinate match. Each entry in EditsList is a pipe-delimited line:
// "old_x1|old_y1|old_x2|old_y2|new_x1|new_y1|new_x2|new_y2" (all in mm).
// Pipe (not comma) is used because the command dispatcher strips commas
// when parsing each JSON array element into this list.
// A selected track is only modified if its current (X1,Y1,X2,Y2) matches an
// entry's old_* values within a small tolerance - this makes the operation
// safe and deterministic instead of relying on a generic geometric transform
// that could go wrong on complex/irregular outlines.
function ApplyTrackEdits(EditsList: TStringList): String;
const
    TolMM = 0.01;
var
    Board       : IPCB_Board;
    Iterator    : IPCB_BoardIterator;
    Prim        : IPCB_Primitive;
    Track       : IPCB_Track;
    i, j        : Integer;
    Fields      : TStringList;
    Line        : String;
    FieldStart  : Integer;
    OldX1, OldY1, OldX2, OldY2 : Double;
    NewX1, NewY1, NewX2, NewY2 : Double;
    CurX1, CurY1, CurX2, CurY2 : Double;
    Matched     : Boolean;
    NApplied, NUnmatched : Integer;
    ResultProps : TStringList;
    OutputLines : TStringList;
begin
    Board := PCBServer.GetCurrentPCBBoard;
    if Board = nil then
    begin
        Result := '{"success": false, "error": "No PCB document is currently active"}';
        Exit;
    end;

    NApplied := 0;
    NUnmatched := 0;
    ResultProps := TStringList.Create;
    Fields := TStringList.Create;
    try
        PCBServer.PreProcess;
        try
            for i := 0 to EditsList.Count - 1 do
            begin
                Line := Trim(EditsList[i]);
                if (Line = '') then continue;

                Fields.Clear;
                FieldStart := 1;
                for j := 1 to Length(Line) + 1 do
                begin
                    if (j > Length(Line)) or (Line[j] = '|') then
                    begin
                        Fields.Add(Trim(Copy(Line, FieldStart, j - FieldStart)));
                        FieldStart := j + 1;
                    end;
                end;
                if Fields.Count < 8 then continue;

                OldX1 := SafeStrToFloat(Fields[0]);
                OldY1 := SafeStrToFloat(Fields[1]);
                OldX2 := SafeStrToFloat(Fields[2]);
                OldY2 := SafeStrToFloat(Fields[3]);
                NewX1 := SafeStrToFloat(Fields[4]);
                NewY1 := SafeStrToFloat(Fields[5]);
                NewX2 := SafeStrToFloat(Fields[6]);
                NewY2 := SafeStrToFloat(Fields[7]);

                Matched := False;

                Iterator := Board.BoardIterator_Create;
                Iterator.AddFilter_ObjectSet(MkSet(eTrackObject));
                Iterator.AddFilter_LayerSet(AllLayers);
                Iterator.AddFilter_Method(eProcessAll);

                Prim := Iterator.FirstPCBObject;
                while (Prim <> nil) do
                begin
                    if Prim.Selected then
                    begin
                        Track := Prim;
                        CurX1 := CoordToMMs(Track.X1);
                        CurY1 := CoordToMMs(Track.Y1);
                        CurX2 := CoordToMMs(Track.X2);
                        CurY2 := CoordToMMs(Track.Y2);

                        if (Abs(CurX1 - OldX1) < TolMM) and (Abs(CurY1 - OldY1) < TolMM) and
                           (Abs(CurX2 - OldX2) < TolMM) and (Abs(CurY2 - OldY2) < TolMM) then
                        begin
                            PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_BeginModify, c_NoEventData);
                            Track.X1 := MMsToCoord(NewX1);
                            Track.Y1 := MMsToCoord(NewY1);
                            Track.X2 := MMsToCoord(NewX2);
                            Track.Y2 := MMsToCoord(NewY2);
                            PCBServer.SendMessageToRobots(Prim.I_ObjectAddress, c_Broadcast, PCBM_EndModify, c_NoEventData);
                            Matched := True;
                        end;
                    end;
                    Prim := Iterator.NextPCBObject;
                end;
                Board.BoardIterator_Destroy(Iterator);

                if Matched then
                    NApplied := NApplied + 1
                else
                    NUnmatched := NUnmatched + 1;
            end;
        finally
            PCBServer.PostProcess;
        end;

        Board.ViewManager_FullUpdate;

        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONInteger(ResultProps, 'applied_count', NApplied);
        AddJSONInteger(ResultProps, 'unmatched_count', NUnmatched);

        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
        Fields.Free;
    end;
end;

// Read-only: for each requested net name, reports every routed Track's
// width/layer (in mm) on the active PCB document. Used to check whether an
// actual routed trace is wide enough for its expected current, since design
// rules only set a minimum and don't reflect what was actually hand-routed.
function GetTrackWidthsByNet(ROOT_DIR, NetNamesList: TStringList): String;
var
    Board       : IPCB_Board;
    Iterator    : IPCB_BoardIterator;
    Prim        : IPCB_Primitive;
    Track       : IPCB_Track;
    i           : Integer;
    NetName     : String;
    NetsArray   : TStringList;
    TracksArray : TStringList;
    ItemProps   : TStringList;
    NetProps    : TStringList;
    ResultProps : TStringList;
    OutputLines : TStringList;
    TCount      : Integer;
begin
    Board := PCBServer.GetCurrentPCBBoard;
    if Board = nil then
    begin
        Result := '{"success": false, "error": "No PCB document is currently active"}';
        Exit;
    end;

    ResultProps := TStringList.Create;
    NetsArray := TStringList.Create;
    try
        for i := 0 to NetNamesList.Count - 1 do
        begin
            NetName := Trim(NetNamesList[i]);
            if (NetName = '') then continue;

            TracksArray := TStringList.Create;
            TCount := 0;
            try
                Iterator := Board.BoardIterator_Create;
                Iterator.AddFilter_ObjectSet(MkSet(eTrackObject));
                Iterator.AddFilter_LayerSet(AllLayers);
                Iterator.AddFilter_Method(eProcessAll);

                Prim := Iterator.FirstPCBObject;
                while (Prim <> nil) do
                begin
                    Track := Prim;
                    if (Track.Net <> nil) and (Track.Net.Name = NetName) then
                    begin
                        TCount := TCount + 1;
                        ItemProps := TStringList.Create;
                        try
                            AddJSONProperty(ItemProps, 'layer', Layer2String(Track.Layer));
                            AddJSONNumber(ItemProps, 'width_mm', CoordToMMs(Track.Width));
                            AddJSONNumber(ItemProps, 'length_mm', CoordToMMs(Sqrt(Sqr(Track.X2-Track.X1) + Sqr(Track.Y2-Track.Y1))));
                            TracksArray.Add(BuildJSONObject(ItemProps, 3));
                        finally
                            ItemProps.Free;
                        end;
                    end;
                    Prim := Iterator.NextPCBObject;
                end;
                Board.BoardIterator_Destroy(Iterator);

                NetProps := TStringList.Create;
                try
                    AddJSONProperty(NetProps, 'net', NetName);
                    AddJSONInteger(NetProps, 'track_count', TCount);
                    if (TracksArray.Count > 0) then
                        NetProps.Add(BuildJSONArray(TracksArray, 'tracks', 2))
                    else
                        NetProps.Add('"tracks": []');
                    NetsArray.Add(BuildJSONObject(NetProps, 1));
                finally
                    NetProps.Free;
                end;
            finally
                TracksArray.Free;
            end;
        end;

        AddJSONBoolean(ResultProps, 'success', True);
        if (NetsArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(NetsArray, 'nets', 0))
        else
            ResultProps.Add('"nets": []');

        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
        NetsArray.Free;
    end;
end;

// Read-only: for every net on the board, reports pad_count and whether any
// copper (Track/Arc/Region/Fill) exists for it anywhere. A net with
// has_copper=false and pad_count>1 is effectively still pure ratsnest
// (unrouted) - used to find what still needs routing across the whole board.
function GetNetRoutingStatus(ROOT_DIR): String;
var
    Board       : IPCB_Board;
    Iterator    : IPCB_BoardIterator;
    Prim        : IPCB_Primitive;
    Pad         : IPCB_Pad;
    RegionVar   : IPCB_Region;
    PolyVar     : IPCB_Polygon;
    PrimNet     : IPCB_Net;
    NetName     : String;
    NetKeys     : TStringList;   // unique net names, in first-seen order
    NetCounts   : TStringList;   // parallel to NetKeys: pad count as string
    NetHasCopper : TStringList;  // net names that have any copper found
    idx         : Integer;
    i           : Integer;
    NetsArray   : TStringList;
    ItemProps   : TStringList;
    ResultProps : TStringList;
    OutputLines : TStringList;
    PadCount    : Integer;
begin
    Board := PCBServer.GetCurrentPCBBoard;
    if Board = nil then
    begin
        Result := '{"success": false, "error": "No PCB document is currently active"}';
        Exit;
    end;

    NetKeys := TStringList.Create;
    NetCounts := TStringList.Create;
    NetHasCopper := TStringList.Create;
    NetHasCopper.Sorted := True;
    NetHasCopper.Duplicates := dupIgnore;
    ResultProps := TStringList.Create;
    NetsArray := TStringList.Create;
    try
        // Pass 1: count pads per net (NetKeys/NetCounts kept in lockstep)
        Iterator := Board.BoardIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(ePadObject));
        Iterator.AddFilter_LayerSet(AllLayers);
        Iterator.AddFilter_Method(eProcessAll);

        Pad := Iterator.FirstPCBObject;
        while (Pad <> nil) do
        begin
            if (Pad.Net <> nil) then
            begin
                NetName := Pad.Net.Name;
                idx := NetKeys.IndexOf(NetName);
                if (idx < 0) then
                begin
                    NetKeys.Add(NetName);
                    NetCounts.Add('1');
                end
                else
                begin
                    PadCount := StrToInt(NetCounts[idx]);
                    NetCounts[idx] := IntToStr(PadCount + 1);
                end;
            end;
            Pad := Iterator.NextPCBObject;
        end;
        Board.BoardIterator_Destroy(Iterator);

        // Pass 2: mark nets that have any copper (Track/Arc/Region/Fill/Polygon pour)
        Iterator := Board.BoardIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(eTrackObject, eArcObject, eRegionObject, eFillObject, ePolyObject));
        Iterator.AddFilter_LayerSet(AllLayers);
        Iterator.AddFilter_Method(eProcessAll);

        Prim := Iterator.FirstPCBObject;
        while (Prim <> nil) do
        begin
            PrimNet := nil;
            case Prim.ObjectId of
                eRegionObject:
                begin
                    RegionVar := Prim;
                    PrimNet := RegionVar.Net;
                end;
                ePolyObject:
                begin
                    PolyVar := Prim;
                    PrimNet := PolyVar.Net;
                end;
            else
                PrimNet := Prim.Net;
            end;

            if (PrimNet <> nil) then
            begin
                NetName := PrimNet.Name;
                if (NetHasCopper.IndexOf(NetName) < 0) then
                    NetHasCopper.Add(NetName);
            end;
            Prim := Iterator.NextPCBObject;
        end;
        Board.BoardIterator_Destroy(Iterator);

        // Build result: only nets with pad_count > 1 and no copper found
        AddJSONBoolean(ResultProps, 'success', True);
        for i := 0 to NetKeys.Count - 1 do
        begin
            NetName := NetKeys[i];
            PadCount := StrToInt(NetCounts[i]);
            if (PadCount > 1) and (NetHasCopper.IndexOf(NetName) < 0) then
            begin
                ItemProps := TStringList.Create;
                try
                    AddJSONProperty(ItemProps, 'net', NetName);
                    AddJSONInteger(ItemProps, 'pad_count', PadCount);
                    NetsArray.Add(BuildJSONObject(ItemProps, 1));
                finally
                    ItemProps.Free;
                end;
            end;
        end;

        AddJSONInteger(ResultProps, 'total_nets_checked', NetKeys.Count);
        if (NetsArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(NetsArray, 'unrouted_nets', 0))
        else
            ResultProps.Add('"unrouted_nets": []');

        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
        NetsArray.Free;
        NetKeys.Free;
        NetCounts.Free;
        NetHasCopper.Free;
    end;
end;

// Read-only: for a given net name, reports which layer(s) have a Region or
// Polygon (plane/pour) primitive for that net, plus each shape's bounding
// box (mm) so the caller can tell a full-board plane from a small local pour.
function GetPlaneLayersForNet(ROOT_DIR, NetName: String): String;
var
    Board       : IPCB_Board;
    Iterator    : IPCB_BoardIterator;
    Prim        : IPCB_Primitive;
    RegionVar   : IPCB_Region;
    PolyVar     : IPCB_Polygon;
    PrimNet     : IPCB_Net;
    Rect        : TCoordRect;
    ShapesArray : TStringList;
    ItemProps   : TStringList;
    ResultProps : TStringList;
    OutputLines : TStringList;
    Kind        : String;
    xorigin, yorigin : Integer;
begin
    Board := PCBServer.GetCurrentPCBBoard;
    if Board = nil then
    begin
        Result := '{"success": false, "error": "No PCB document is currently active"}';
        Exit;
    end;

    xorigin := Board.XOrigin;
    yorigin := Board.YOrigin;

    ResultProps := TStringList.Create;
    ShapesArray := TStringList.Create;
    try
        Iterator := Board.BoardIterator_Create;
        Iterator.AddFilter_ObjectSet(MkSet(eRegionObject, ePolyObject));
        Iterator.AddFilter_LayerSet(AllLayers);
        Iterator.AddFilter_Method(eProcessAll);

        Prim := Iterator.FirstPCBObject;
        while (Prim <> nil) do
        begin
            PrimNet := nil;
            Kind := '';
            if (Prim.ObjectId = eRegionObject) then
            begin
                RegionVar := Prim;
                PrimNet := RegionVar.Net;
                Kind := 'Region';
            end
            else if (Prim.ObjectId = ePolyObject) then
            begin
                PolyVar := Prim;
                PrimNet := PolyVar.Net;
                Kind := 'Polygon';
            end;

            if (PrimNet <> nil) and (PrimNet.Name = NetName) then
            begin
                Rect := Prim.BoundingRectangle;
                ItemProps := TStringList.Create;
                try
                    AddJSONProperty(ItemProps, 'kind', Kind);
                    AddJSONProperty(ItemProps, 'layer', Layer2String(Prim.Layer));
                    AddJSONNumber(ItemProps, 'bbox_min_x_mm', CoordToMMs(Rect.Left - xorigin));
                    AddJSONNumber(ItemProps, 'bbox_min_y_mm', CoordToMMs(Rect.Bottom - yorigin));
                    AddJSONNumber(ItemProps, 'bbox_max_x_mm', CoordToMMs(Rect.Right - xorigin));
                    AddJSONNumber(ItemProps, 'bbox_max_y_mm', CoordToMMs(Rect.Top - yorigin));
                    AddJSONNumber(ItemProps, 'bbox_width_mm', CoordToMMs(Rect.Right - Rect.Left));
                    AddJSONNumber(ItemProps, 'bbox_height_mm', CoordToMMs(Rect.Top - Rect.Bottom));
                    ShapesArray.Add(BuildJSONObject(ItemProps, 1));
                finally
                    ItemProps.Free;
                end;
            end;
            Prim := Iterator.NextPCBObject;
        end;
        Board.BoardIterator_Destroy(Iterator);

        AddJSONBoolean(ResultProps, 'success', True);
        AddJSONProperty(ResultProps, 'net', NetName);
        AddJSONInteger(ResultProps, 'shape_count', ShapesArray.Count);
        if (ShapesArray.Count > 0) then
            ResultProps.Add(BuildJSONArray(ShapesArray, 'shapes', 0))
        else
            ResultProps.Add('"shapes": []');

        OutputLines := TStringList.Create;
        try
            OutputLines.Text := BuildJSONObject(ResultProps);
            Result := OutputLines.Text;
        finally
            OutputLines.Free;
        end;
    finally
        ResultProps.Free;
        ShapesArray.Free;
    end;
end;
